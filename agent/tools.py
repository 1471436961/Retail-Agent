"""Platform tool discovery entry point."""

from support_agent.adapters.customer_tools import CustomerTools as _CustomerTools


class Tools(_CustomerTools):
    """Expose the original lookup and extended retail tools to the platform."""
