"""Model-driven turn orchestration behind the original platform factory."""

from tau2.data_model.message import AssistantMessage, MultiToolMessage, SystemMessage
from support_agent.config import policy_text
from support_agent.state import (finished_message, initial_state, is_finished_message,
                                 restored_messages, serialized_messages)


# Preserve the original SDK methods for compatibility, but offer the model one
# contextual identity tool rather than several overlapping low-level routes.
_IDENTITY_PRIMITIVES = {"lookup_customer", "find_user_id_by_email", "find_user_id_by_name_zip", "get_user_details"}


class IncompleteModelResponse(RuntimeError):
    """The provider stopped before completing the proposed reply or tool batch."""


def _require_complete_response(response):
    raw = response.raw_data or {}
    choices = raw.get("choices") or []
    # The SDK returns choices[0]; unused alternatives do not determine whether
    # this AssistantMessage is complete.
    truncated = bool(choices and isinstance(choices[0], dict)
                     and choices[0].get("finish_reason") == "length")
    if raw.get("status") == "incomplete" or truncated:
        reason = "status=incomplete" if raw.get("status") == "incomplete" else "finish_reason=length"
        raise IncompleteModelResponse(
            f"The platform model returned an incomplete response ({reason}); "
            "no proposed tools were dispatched"
        )


class CustomerAgent:
    """Keep conversation history; let the model choose replies and tools."""

    def __init__(self, context):
        self.context = context
        available = context.action_interface.available
        self.tools = tuple(tool for tool in available if tool.name not in _IDENTITY_PRIMITIVES)
        self._finish_action = next(tool for tool in available if tool.name == "finish_response")
        self.model = context.model_gateway.available_models[0]
        self.model_args = {}
        # Fixed options belong to the platform. Only explicit choices need a
        # caller value; never copy a model name or token limit from a kit.
        for config in getattr(context.model_gateway, "models", ()):
            if config.model == self.model:
                for name, rule in config.constrained_args.items():
                    if isinstance(rule, dict) and set(rule) == {"one_of"}:
                        if not rule["one_of"]:
                            raise ValueError("The platform supplied an empty model option")
                        self.model_args[name] = rule["one_of"][0]
                break
        self.policy = policy_text()

    def get_init_state(self, message_history=None):
        return initial_state(message_history)

    def is_stop(self, message):
        """Honor the model's explicit finish action; never infer completion from prose."""
        return is_finished_message(message)

    def generate_next_message(self, message, state):
        history = restored_messages(state)
        if isinstance(message, MultiToolMessage):
            history.extend(message.tool_messages)
        else:
            history.append(message)
        response = self.context.model_gateway.generate(
            model=self.model,
            messages=[SystemMessage(role="system", content=self.policy), *history],
            actions=self.tools,
            call_name="retail_agent_response",
            **self.model_args,
        )
        # No intent parser, candidate JSON, user rewriting or hidden retries.
        # Gateway exceptions remain observable; do not fabricate a business reply.
        if not isinstance(response, AssistantMessage):
            raise TypeError("The platform model gateway did not return AssistantMessage")
        _require_complete_response(response)
        if response.tool_calls:
            finish = [call for call in response.tool_calls if call.name == "finish_response"]
            remaining = [call for call in response.tool_calls if call.name != "finish_response"]
            if finish and not remaining:
                messages = []
                for call in finish:
                    arguments = self._finish_action.params.model_validate(call.arguments).model_dump()
                    messages.append(self._finish_action(**arguments)["message"])
                response = finished_message(response, "\n\n".join(messages))
            elif finish:
                # A completion proposed alongside real calls must wait for those
                # results. Dispatch the calls without claiming that they succeeded.
                response = response.model_copy(update={"tool_calls": remaining})
        if response.tool_calls and response.content:
            # A provider preamble is not a separate customer reply. Dispatch
            # the function call and wait for evidence before saying more.
            response = response.model_copy(update={"content": None})
        history.append(response)
        next_state = {**state, "turn": state.get("turn", 0) + 1,
                      "customer_id": state.get("customer_id"),
                      "pending_call_id": response.tool_calls[0].id if response.tool_calls and len(response.tool_calls) == 1 else None,
                      "finished": is_finished_message(response),
                      "messages": serialized_messages(history)}
        return response, next_state
