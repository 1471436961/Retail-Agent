"""Thin tau2 adapter around the platform-independent turn reducer."""

from support_agent.protocol import ToolOutcome, TurnInput
from support_agent.state import InvalidState, clone_state, initial_state, quarantine_state
from support_agent.proposals import InvalidProposal
from support_agent.domain.task_graph import InvalidTaskPlan
from support_agent.write_session import InvalidWrite
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
        except (InvalidState, InvalidProposal, InvalidTaskPlan, InvalidWrite):
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

    def plan_tasks(self, state, requests):
        """Internal M3.4 request plan, never a confirmation or execution."""
        from support_agent.tasks import present_task_plan
        return self._present(state, requests, present_task_plan)

    def execute_operation(self, state, version, specification, runtime=None):
        """Explicit internal M3.5 port; the factory supplies no write runtime."""
        from support_agent.write_session import execute_operation
        if isinstance(state, dict) and "session_block" in state:
            return {"decision": "deny", "code": "invalid_state", "message": "Session evidence needs review.",
                    "rules": ["EN-02"], "details": {"write_authorized": False}}, state
        try:
            return execute_operation(state, version, specification, runtime)
        except (InvalidState, InvalidProposal, InvalidTaskPlan, InvalidWrite):
            return {"decision": "deny", "code": "invalid_state", "message": "Write evidence needs review.",
                    "rules": ["EN-02"], "details": {"write_authorized": False, "state_error": True}}, quarantine_state(state, "invalid_state")

    def reconcile_operation(self, state, call_id, runtime=None):
        """Internal readonly verification; never retries a recorded write."""
        from support_agent.write_session import reconcile_operation
        if isinstance(state, dict) and "session_block" in state:
            return {"decision": "deny", "code": "invalid_state", "message": "Session evidence needs review.",
                    "rules": ["EN-02"], "details": {"write_authorized": False}}, state
        try:
            return reconcile_operation(state, call_id, runtime)
        except (InvalidState, InvalidProposal, InvalidTaskPlan, InvalidWrite):
            return {"decision": "deny", "code": "invalid_state", "message": "Write evidence needs review.",
                    "rules": ["EN-02"], "details": {"write_authorized": False, "state_error": True}}, quarantine_state(state, "invalid_state")

    def submit_operation(self, state, version, specification, runtime=None):
        """Trusted workflow SDK reply/state pair; no model dispatch surface.

        The same returned state contains the original sent/result/readback
        evidence. A customer reply never replaces or creates that evidence.
        """
        result, next_state = self.execute_operation(state, version, specification, runtime)
        if isinstance(next_state, dict) and "session_block" in next_state:
            return self._blocked_reply(next_state)
        if result["code"] == "write_verified":
            action = specification["action"]
            text = ("Your return request was accepted and verified. This does not confirm refund settlement or arrival."
                    if action == "return" else "The requested operation was accepted and its visible result was verified.")
        elif result["code"] == "write_rejected":
            text = "The requested operation was rejected. It has not been retried."
        elif result["code"] in {"write_result_unknown", "write_sent_unresolved", "write_result_unresolved", "checkpoint_unresolved"}:
            text = "The operation outcome is unresolved. I will not repeat it or report it as completed."
        else:
            text = "The requested operation has not been verified. Its parameters, consent or current facts need review before proceeding."
        next_state["history"].append({"role": "assistant", "content": text})
        return AssistantMessage(role="assistant", content=text), clone_state(next_state)

    def _present(self, state, specification, presenter):
        if isinstance(state, dict) and "session_block" in state:
            return self._blocked_reply(state)
        try:
            decision, next_state = presenter(state, specification)
        except InvalidState:
            return self._blocked_reply(quarantine_state(state, "invalid_state"))
        except (InvalidProposal, InvalidTaskPlan):
            # Invalid workflow construction may be repaired; keep the valid
            # session evidence and do not render internal exception details.
            next_state = clone_state(state)
            text = "A complete proposal could not be prepared. Its parameters and accepted evidence need review before confirmation."
            if presenter.__name__ == "present_task_plan":
                text = "The requested operation plan needs review of its targets and accepted evidence before proceeding."
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
        except (InvalidState, InvalidProposal, InvalidTaskPlan, InvalidWrite):
            return self._blocked_reply(quarantine_state(state, "invalid_state"))
        if decision.calls:
            calls = [
                ToolCall(id=call.id, name=call.name, arguments=call.arguments, requestor="assistant")
                for call in decision.calls
            ]
            return AssistantMessage(role="assistant", tool_calls=calls), next_state
        return AssistantMessage(role="assistant", content=decision.text), next_state
