"""Platform entry point; application behavior lives in the support_agent package."""

from support_agent.application import CustomerAgent
from support_agent.adapters.semantic_model import runtime_adapter
from tau2.hyper.agent_context import get_agent_context


def create_agent():
    """Create a fresh agent; never keep conversation state in module globals."""
    context = get_agent_context()
    return CustomerAgent(context=context, model_adapter=runtime_adapter(context))
