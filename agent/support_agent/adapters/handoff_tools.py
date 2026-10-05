"""Conversation transfer is an internal mutating surface, excluded from models."""
import json
from tau2.hyper.client_api import ClientAPIToolKitBase
from tau2.environment.toolkit import ToolType, is_tool
from support_agent.state import clone_state
from support_agent.workflow_limits import check_workflow_argument
from support_agent.handoff_session import run_handoff_workflow


class HandoffTools(ClientAPIToolKitBase):
    # Tool classification and SDK replay metadata are separate contracts.
    # Transfers change conversation routing; GENERIC in the teaching example
    # is not a requirement to hide that effect or a duplicate-send guard.
    @is_tool(ToolType.WRITE, mutates_state=True)
    def handoff_workflow(self, session_json: str) -> dict:
        """Transfer on an explicit actual user request with an evidence-derived summary.

        Conversation ID comes only from Client API context. No caller-supplied
        summary, ID, arbitrary endpoint, acceptance flag or automatic retry.
        """
        check_workflow_argument(session_json)
        return run_handoff_workflow(clone_state(json.loads(session_json)), self.client_api, self._workflow_claims)
