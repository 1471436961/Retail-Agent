"""Platform-independent turn types and the currently approved tool schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from support_agent.config import DOMAIN
from support_agent.domain.customer import find_email


MAX_TOOL_CALLS_PER_MESSAGE = 8
MAX_CANDIDATE_ATTEMPTS = 8


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
    if action.name != "lookup_customer":
        raise InvalidAction("Unsupported tool")
    if not isinstance(action.id, str) or not action.id:
        raise InvalidAction("Tool call ID is required")
    if not isinstance(action.arguments, dict) or set(action.arguments) != {"customer_id", "email"}:
        raise InvalidAction("Invalid lookup arguments")
    if any(not isinstance(value, str) for value in action.arguments.values()):
        raise InvalidAction("Lookup arguments must be strings")
    if DOMAIN == "retail_plus" and find_email(action.arguments["email"]) != action.arguments["email"]:
        raise InvalidAction("Retail lookup requires an independently supplied email")


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
