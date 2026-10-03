"""Thin tau2 adapter around the platform-independent turn reducer."""

from support_agent.protocol import ToolOutcome, TurnInput
from support_agent.state import InvalidState, clone_state, initial_state, quarantine_state
from support_agent.proposals import InvalidProposal
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
        try:
            return initial_state(message_history)
        except (InvalidState, InvalidProposal):
            return quarantine_state({"unrestored_history": message_history}, "invalid_history")

    def _blocked_reply(self, state):
        # Every subsequent platform operation remains blocked. No automatic
        # reset, history repair, API/model call or pending-operation replay.
        return AssistantMessage(role="assistant", content="Session evidence is inconsistent. Processing is stopped; the original conversation must be reviewed before continuing."), state

    def present_proposal(self, state, specification):
        """Internal workflow presentation; never a model tool or a business write."""
        from support_agent.proposals import present_proposal
        return self._present(state, specification, present_proposal)

    def present_proposals(self, state, specifications):
        """Internal M3.3 entry: separately selectable complete operations."""
        from support_agent.proposals import present_proposals
        return self._present(state, specifications, present_proposals)

    def _present(self, state, specification, presenter):
        if isinstance(state, dict) and "session_block" in state:
            return self._blocked_reply(state)
        try:
            decision, next_state = presenter(state, specification)
        except InvalidState:
            return self._blocked_reply(quarantine_state(state, "invalid_state"))
        except InvalidProposal:
            # Invalid workflow construction may be repaired; keep the valid
            # session evidence and do not render internal exception details.
            next_state = clone_state(state)
            text = "A complete proposal could not be prepared. Its parameters and accepted evidence need review before confirmation."
            next_state["history"].append({"role": "assistant", "content": text})
            return AssistantMessage(role="assistant", content=text), next_state
        return AssistantMessage(role="assistant", content=decision.text), next_state

    def generate_next_message(self, message, state):
        """Convert one platform message and return exactly text or tool calls."""
        if isinstance(state, dict) and "session_block" in state:
            return self._blocked_reply(state)
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
        try:
            decision, next_state = advance(turn, state, model_adapter=self.model_adapter)
        except (InvalidState, InvalidProposal):
            return self._blocked_reply(quarantine_state(state, "invalid_state"))
        if decision.calls:
            calls = [
                ToolCall(id=call.id, name=call.name, arguments=call.arguments, requestor="assistant")
                for call in decision.calls
            ]
            return AssistantMessage(role="assistant", tool_calls=calls), next_state
        return AssistantMessage(role="assistant", content=decision.text), next_state
