"""Internal confirmed cancellation; no standalone refund or model dispatch."""
import json
from support_agent.workflow_limits import check_workflow_argument
from support_agent.cancellation_session import run_cancellation_workflow
from support_agent.state import clone_state
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class CancellationTools(ClientAPIToolKitBase):
    @is_tool(ToolType.WRITE)
    def cancellation_workflow(self, session_json: str) -> dict:
        """Prepare or submit one owned order cancellation with an accepted reason.

        Actual user sources, full recap/confirmation, shared claims and original
        refund rows are required. No arbitrary HTTP path or refund destination.
        """
        from support_agent.adapters.write_runtime import ensure_business_active
        ensure_business_active(self.client_api, self._workflow_claims)
        check_workflow_argument(session_json)
        return run_cancellation_workflow(clone_state(json.loads(session_json)), self.client_api, self._workflow_claims)
