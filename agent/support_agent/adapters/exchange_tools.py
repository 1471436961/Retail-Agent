"""Trusted complete exchange application; never a model candidate surface."""
import json
from support_agent.exchange_session import run_exchange_workflow
from support_agent.workflow_limits import check_workflow_argument
from support_agent.adapters.write_runtime import ensure_business_active
from support_agent.state import clone_state
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class ExchangeTools(ClientAPIToolKitBase):
    @is_tool(ToolType.WRITE)
    def exchange_workflow(self, session_json: str) -> dict:
        """Host-owned complete delivered-order exchange intake/confirmation/readback.

        No model dispatch, arbitrary endpoint, quantity, partial write, supplied
        criteria/confirmed flag, standalone charge/refund or return API.
        """
        ensure_business_active(self.client_api, self._workflow_claims)
        check_workflow_argument(session_json)
        return run_exchange_workflow(clone_state(json.loads(session_json)), self.client_api, self._workflow_claims)
