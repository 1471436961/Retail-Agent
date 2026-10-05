"""Ordered internal business kinds; handoff has a separate lifecycle.

This inventory is trusted code, never user/model input or write authority.
Adding a kind also requires its boundary rules, producer, schema and SDK tool.
"""

WORKFLOW_KINDS = ("address", "payment", "cancellation", "items", "returns")
