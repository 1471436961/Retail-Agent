"""Platform tool discovery entry point."""

from support_agent.adapters.customer_tools import CustomerTools as _CustomerTools


class Tools(_CustomerTools):
    """Expose eight reads and internal address/payment/cancellation/handoff/items/returns/exchange workflows."""
