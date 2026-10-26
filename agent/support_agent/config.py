"""Read the exported project domain; never infer a domain from a customer ID."""
import json
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = json.loads((AGENT_ROOT / "agent.json").read_text(encoding="utf-8"))["domain"]


def policy_text():
    return (AGENT_ROOT / "policy.md").read_text(encoding="utf-8")
