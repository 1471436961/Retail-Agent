"""Platform-independent turn types and the currently approved tool schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from support_agent.config import DOMAIN
from support_agent.domain.identity import PROOF_FIELDS, verification_inputs
from support_agent.workflow_registry import WORKFLOW_KINDS


MAX_TOOL_CALLS_PER_MESSAGE = 8
MAX_CANDIDATE_ATTEMPTS = 8
# Internal shape inventory only; model authorization remains READ_TOOL_FIELDS.
WORKFLOW_TOOL_NAMES = frozenset(kind + "_workflow" for kind in WORKFLOW_KINDS) | {"handoff_workflow"}
VERIFICATION_FIELDS = {"customer_id", *PROOF_FIELDS}
READ_TOOL_FIELDS = {
    "lookup_customer": {"customer_id", "email"},
    "verify_customer": VERIFICATION_FIELDS,
    "read_customer_profile": VERIFICATION_FIELDS,
    "get_order": VERIFICATION_FIELDS | {"order_id"},
    "list_customer_orders": VERIFICATION_FIELDS | {"status"},
    "list_products": VERIFICATION_FIELDS,
    "get_product": VERIFICATION_FIELDS | {"product_id"},
    "get_item": VERIFICATION_FIELDS | {"item_id"},
}


class InvalidAction(ValueError):
    """An unrecognised or malformed candidate action must not reach a tool."""


@dataclass(frozen=True)
class ToolOutcome:
    id: str
    content: str
    error: bool = False


@dataclass(frozen=True)
class TurnInput:
    kind: Literal["user", "tools"]
    content: str = ""
    outcomes: tuple[ToolOutcome, ...] = ()

    def __post_init__(self):
        if self.kind not in ("user", "tools"):
            raise ValueError("Unsupported input kind")
        if self.kind == "user" and self.outcomes:
            raise ValueError("A user turn cannot carry tool outcomes")
        if self.kind == "tools" and self.content:
            raise ValueError("A tool turn cannot carry user text")


@dataclass(frozen=True)
class ToolAction:
    id: str
    name: str
    arguments: dict[str, str]


def validate_tool_action(action: ToolAction) -> None:
    """Reject unknown actions and arguments before creating a platform call."""
    if action.name in WORKFLOW_TOOL_NAMES:
        if (not isinstance(action.id, str) or not action.id or not isinstance(action.arguments, dict)
                or set(action.arguments) != {"session_json"} or not isinstance(action.arguments["session_json"], str)):
            raise InvalidAction("Invalid internal workflow call")
        from support_agent.workflow_limits import check_workflow_argument
        try:
            check_workflow_argument(action.arguments["session_json"])
        except ValueError as exc:
            raise InvalidAction("Internal workflow tool argument budget exceeded") from exc
        return
    if action.name not in READ_TOOL_FIELDS:
        raise InvalidAction("Unsupported tool")
    if not isinstance(action.id, str) or not action.id:
        raise InvalidAction("Tool call ID is required")
    if not isinstance(action.arguments, dict) or set(action.arguments) != READ_TOOL_FIELDS[action.name]:
        raise InvalidAction("Invalid read arguments")
    if any(not isinstance(value, str) for value in action.arguments.values()):
        raise InvalidAction("Lookup arguments must be strings")
    if DOMAIN == "retail_plus":
        try:
            verification_inputs(**{k: action.arguments.get(k, "") for k in PROOF_FIELDS})
        except ValueError as exc:
            raise InvalidAction("Retail read requires independent verification") from exc
    for key in ("order_id", "product_id", "item_id"):
        if key in action.arguments and not action.arguments[key].strip():
            raise InvalidAction("Read target ID is required")


@dataclass(frozen=True)
class Decision:
    text: str | None = None
    calls: tuple[ToolAction, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if (self.text is None) == (not self.calls):
            raise InvalidAction("Choose text or tool calls, not both or neither")
        if self.text is not None and (not isinstance(self.text, str) or not self.text):
            raise InvalidAction("Reply text must be nonempty")
        if len(self.calls) > MAX_TOOL_CALLS_PER_MESSAGE:
            raise InvalidAction("Too many tool calls in one turn")
        seen: set[str] = set()
        for action in self.calls:
            validate_tool_action(action)
            if action.id in seen:
                raise InvalidAction("Duplicate tool call ID")
            seen.add(action.id)


def decision_from_candidate(candidate: object, *, call_id: str) -> Decision:
    """Validate an internal candidate shape before an adapter may emit it.

    This is deliberately not a claim about the platform model gateway format.
    A future gateway adapter must first normalize its actual response to this
    small internal shape.
    """
    if not isinstance(candidate, dict):
        raise InvalidAction("Candidate must be an object")
    if candidate.get("type") == "reply" and set(candidate) == {"type", "text"}:
        return Decision(text=candidate["text"])
    if candidate.get("type") == "tool" and set(candidate) == {"type", "name", "arguments"}:
        if candidate["name"] not in READ_TOOL_FIELDS:
            raise InvalidAction("Model candidates cannot dispatch a business workflow")
        return Decision(calls=(ToolAction(id=call_id, name=candidate["name"], arguments=candidate["arguments"]),))
    raise InvalidAction("Unsupported candidate shape")


def select_candidate(next_candidate: Callable[[], object], *, call_id: str, max_attempts: int = 2) -> Decision:
    """Bound normalization attempts; invalid suggestions never become calls."""
    if not 1 <= max_attempts <= MAX_CANDIDATE_ATTEMPTS:
        raise ValueError("Invalid candidate attempt limit")
    for _ in range(max_attempts):
        try:
            return decision_from_candidate(next_candidate(), call_id=call_id)
        except InvalidAction:
            continue
    return Decision(text="I cannot safely complete that action with the information available.")
