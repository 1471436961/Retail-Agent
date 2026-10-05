"""Platform tool discovery entry point."""

from support_agent.adapters.customer_tools import CustomerTools


class Tools(CustomerTools):
    """Expose eight reads and internal address/payment/cancellation/handoff workflows."""
