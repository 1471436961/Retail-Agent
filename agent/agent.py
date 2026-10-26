"""Platform factory entry point; application code stays in support_agent."""

from support_agent.application import CustomerAgent
from tau2.hyper.agent_context import get_agent_context


def create_agent():
    """Keep the original zero-argument platform factory contract."""
    return CustomerAgent(context=get_agent_context())
