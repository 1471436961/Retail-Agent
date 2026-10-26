"""Model-driven turn orchestration behind the original platform factory."""

from tau2.data_model.message import AssistantMessage, MultiToolMessage, SystemMessage
from support_agent.config import policy_text
from support_agent.state import initial_state, restored_messages, serialized_messages


class CustomerAgent:
    """Keep conversation history; let the model choose replies and tools."""

    def __init__(self, context):
        self.context = context
        self.tools = context.action_interface.available
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
        if response.tool_calls and response.content:
            # A provider preamble is not a separate customer reply. Dispatch
            # the function call and wait for evidence before saying more.
            response = response.model_copy(update={"content": None})
        history.append(response)
        next_state = {**state, "turn": state.get("turn", 0) + 1,
                      "customer_id": state.get("customer_id"),
                      "pending_call_id": response.tool_calls[0].id if response.tool_calls and len(response.tool_calls) == 1 else None,
                      "messages": serialized_messages(history)}
        return response, next_state
