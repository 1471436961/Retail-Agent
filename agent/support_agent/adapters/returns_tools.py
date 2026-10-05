"""Internal complete-return dispatch, never a model candidate surface."""
import json
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.workflow_limits import check_workflow_argument
from support_agent.state import clone_state
from support_agent.returns_session import run_returns_workflow


class ReturnsTools(ClientAPIToolKitBase):
    def __init__(self, client_api, *, claims=None):
        super().__init__(client_api)
        if claims is not None and not isinstance(claims, SessionClaims):
            raise TypeError('Returns claims require a trusted SessionClaims store')
        self._workflow_claims=claims if claims is not None else SessionClaims()

    @is_tool(ToolType.WRITE)
    def returns_workflow(self,session_json: str) -> dict:
        """Internal return application from an original dispatch snapshot.

        No caller-supplied amount, refund API, confirmation, condition or HTTP
        path. A new empty claim store is not durable deduplication.
        """
        from support_agent.adapters.write_runtime import ensure_business_active
        ensure_business_active(self.client_api, self._workflow_claims)
        check_workflow_argument(session_json)
        return run_returns_workflow(clone_state(json.loads(session_json)),self.client_api,self._workflow_claims)
