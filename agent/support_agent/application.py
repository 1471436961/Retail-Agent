"""Thin tau2 adapter around the platform-independent turn reducer."""

from support_agent.protocol import ToolOutcome, TurnInput
from support_agent.state import initial_state
from support_agent.turns import advance
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall


class CustomerAgent:
    """Deterministic t1 lookup example, not a complete p1/t2 business solution."""

    def __init__(self, context=None, model_adapter=None):
        # Runtime capabilities are instance-local, never persisted in JSON state.
        self.context = context
        # Explicit injection is required; factory defaults never call a model.
        self.model_adapter = model_adapter

    def get_init_state(self, message_history=None):
        return initial_state(message_history)

    def generate_next_message(self, message, state):
        """Convert one platform message and return exactly text or tool calls."""
        if isinstance(message, MultiToolMessage):
            turn = TurnInput(
                kind="tools",
                outcomes=tuple(
                    ToolOutcome(id=item.id, content=item.content, error=bool(item.error))
                    for item in message.tool_messages
                ),
            )
        else:
            if getattr(message, "role", None) != "user":
                raise ValueError("Unsupported platform message: expected user or multi-tool results")
            turn = TurnInput(kind="user", content=message.content or "")
        decision, next_state = advance(turn, state, model_adapter=self.model_adapter)
        if decision.calls:
            calls = [
                ToolCall(id=call.id, name=call.name, arguments=call.arguments, requestor="assistant")
                for call in decision.calls
            ]
            return AssistantMessage(role="assistant", tool_calls=calls), next_state
        return AssistantMessage(role="assistant", content=decision.text), next_state
