"""Tool registration translates the model-facing contract into API calls."""

import json

from support_agent.adapters.customer_api import read_customer, verify_and_read_customer
from support_agent.adapters.read_tools import ReadTools
from support_agent.adapters.address_tools import AddressTools
from support_agent.adapters.payment_tools import PaymentTools
from support_agent.adapters.cancellation_tools import CancellationTools
from support_agent.adapters.handoff_tools import HandoffTools
from support_agent.adapters.items_tools import ItemsTools
from support_agent.adapters.returns_tools import ReturnsTools
from support_agent.adapters.exchange_tools import ExchangeTools
from support_agent.config import DOMAIN
from tau2.environment.toolkit import ToolType, is_tool


class CustomerTools(AddressTools, PaymentTools, CancellationTools, HandoffTools, ItemsTools, ReturnsTools, ExchangeTools, ReadTools):
    """Add reviewed read/write tools here as you implement business workflows."""

    def use_tool(self, tool_name: str, /, **kwargs) -> str:
        """Serialize once at the SDK boundary, preserving JSON scalar types.

        Public SDK dispatch receives text. Internal workflow methods retain
        typed objects; Environment must not recursively stringify their values.
        """
        result = super().use_tool(tool_name, **kwargs)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    @is_tool(ToolType.READ)
    def lookup_customer(self, customer_id: str, email: str = "") -> dict:
        """Read a customer. Retail requires independently supplied email verification."""
        if DOMAIN == "retail_plus":
            return verify_and_read_customer(self.client_api, customer_id, email)
        return read_customer(self.client_api, customer_id)
