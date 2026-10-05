"""Internal complete-list item change, never a model candidate surface."""
import json
from support_agent.items_session import run_items_workflow
from support_agent.workflow_limits import check_workflow_argument
from support_agent.adapters.write_runtime import ensure_business_active
from support_agent.state import clone_state
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class ItemsTools(ClientAPIToolKitBase):
    @is_tool(ToolType.WRITE)
    def items_workflow(self, session_json: str) -> dict:
        """Host complete-list intake/recap/fresh consent/one submission/readback.

        No arbitrary endpoint, quantity, partial write, confirmed flag, return
        or exchange API. Actual role history supplies all customer conditions.
        """
        ensure_business_active(self.client_api, self._workflow_claims)
        check_workflow_argument(session_json)
        return run_items_workflow(clone_state(json.loads(session_json)), self.client_api, self._workflow_claims)
