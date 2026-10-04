"""Internal payment tool; no model dispatch or standalone charge/refund API."""
import json
from support_agent.workflow_limits import check_workflow_argument
from support_agent.payment_session import run_payment_workflow
from support_agent.state import clone_state
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class PaymentTools(ClientAPIToolKitBase):
    @is_tool(ToolType.WRITE)
    def payment_workflow(self, session_json: str) -> dict:
        """Prepare or submit one complete user-confirmed saved-method switch.

        Uses the same trusted toolkit Client API and SessionClaims as address
        writes. No arbitrary endpoint, confirmed flag, or partial payment.
        """
        check_workflow_argument(session_json)
        return run_payment_workflow(clone_state(json.loads(session_json)), self.client_api, self._workflow_claims)
