"""Platform tool discovery entry point."""

from support_agent.adapters.customer_tools import CustomerTools


class Tools(CustomerTools):
    """Expose eight reads and internal confirmed-address/payment workflows."""
