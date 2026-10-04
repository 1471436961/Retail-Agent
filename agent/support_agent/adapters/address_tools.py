"""Address-only workflow tool, reproducible on a new toolkit/backend replay."""
import json

from support_agent.address_session import run_address_workflow
from support_agent.workflow_limits import check_workflow_argument
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.state import clone_state
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class AddressTools(ClientAPIToolKitBase):
    def __init__(self, client_api, *, claims=None):
        super().__init__(client_api)
        # A host recreating toolkits for the same live backend must explicitly
        # retain this trusted store. A fresh store is not durable deduplication.
        if claims is not None and not isinstance(claims, SessionClaims):
            raise TypeError("Address claims require a trusted SessionClaims store")
        self._workflow_claims = claims if claims is not None else SessionClaims()

    @is_tool(ToolType.WRITE)
    def address_workflow(self, session_json: str) -> dict:
        """Internal address intake/submission; never a model candidate surface.

        Preserve original role messages and complete consent/state. Preparation
        only reads and recaps; execution refreshes confirmed exact address
        records, sends each at most once and independently reads back results.
        No payment, cancellation, item, return, transfer or arbitrary HTTP path.
        """
        check_workflow_argument(session_json)  # Before parsing or any API call.
        state = clone_state(json.loads(session_json))
        return run_address_workflow(state, self.client_api, self._workflow_claims)
