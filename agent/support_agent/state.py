"""JSON-only session state; no SDK objects or module-global conversation data."""

import json
import re

from support_agent.domain.customer import find_customer_id, verified_lookup_result
from support_agent.protocol import InvalidAction, ToolAction, ToolOutcome, validate_tool_action


SCHEMA_VERSION = 1


class InvalidState(ValueError):
    """Reject incomplete or inconsistent state at the session boundary."""


def finish_pending(state: dict, status: str) -> None:
    call_id = state["pending_call_id"]
    if call_id is not None:
        state["pending_calls"].pop(call_id, None)
        for operation in reversed(state["operations"]):
            if operation["call_id"] == call_id and operation["status"] == "sent":
                operation["status"] = status
                break
    state["pending_call_id"] = None


def record_lookup_call(state: dict, action: ToolAction) -> None:
    """The t1 workflow supports one outstanding read, never a tool chain."""
    validate_tool_action(action)
    if any(operation["call_id"] == action.id for operation in state["operations"]):
        raise InvalidAction("Reused tool call ID")
    finish_pending(state, "unknown")
    state["identity"] = {"verified": False, "customer_id": None}
    state["pending_call_id"] = action.id
    state["pending_calls"][action.id] = {"name": action.name, "arguments": dict(action.arguments), "mutates": False}
    state["operations"].append({"call_id": action.id, "name": action.name, "mutates": False, "status": "sent"})
    state["tool_calls_since_user"] += 1


def consume_lookup_results(state: dict, outcomes) -> tuple[str, str]:
    """Apply complete-batch checks in live turns and restoration.

    Return (status, content). ``none`` has no pending lookup; ``unknown``
    has no uniquely associated result. Both return empty content.
    ``failed`` and ``mismatch`` retain the associated raw result for
    diagnostics; it is unverified and must not be presented as customer
    facts. Only ``succeeded`` returns verified content for the reply.
    """
    call_id = state["pending_call_id"]
    if call_id is None:
        return "none", ""
    pending = state["pending_calls"].get(call_id)
    if len(outcomes) != 1 or outcomes[0].id != call_id or not isinstance(pending, dict):
        finish_pending(state, "unknown")
        return "unknown", ""
    result = outcomes[0]
    if result.error:
        finish_pending(state, "failed")
        return "failed", result.content
    verified_id = verified_lookup_result(result.content, pending["arguments"])
    if verified_id is None:
        finish_pending(state, "unknown")
        return "mismatch", result.content
    state["identity"] = {"verified": True, "customer_id": verified_id}
    state["customer_id"] = verified_id
    finish_pending(state, "succeeded")
    return "succeeded", result.content


def result_history(outcomes) -> dict:
    entries = [{"role": "tool", "id": result.id, "content": result.content, "error": result.error} for result in outcomes]
    # Keep empty and multiple results together; flattening loses ambiguity.
    return entries[0] if len(entries) == 1 else {"role": "tools", "tool_messages": entries}


def _tool_entry(message):
    def value(key, default=None):
        return message.get(key, default) if isinstance(message, dict) else getattr(message, key, default)
    return {"role": "tool", "id": value("id") if isinstance(value("id"), str) else "",
            "content": value("content") if isinstance(value("content"), str) else "",
            "error": bool(value("error", False))}


def _history_entry(message):
    """Keep platform history as evidence, never replay its tool calls."""
    role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if role not in {"user", "assistant", "tool"}:
        return None
    entry = {"role": role, "content": content if isinstance(content, str) else ""}
    if role == "tool":
        return _tool_entry(message)
    if role == "assistant":
        calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        if calls:
            entry["tool_call_ids"] = [
                call.get("id", "") if isinstance(call, dict) else getattr(call, "id", "")
                for call in calls
            ]
            entry["tool_calls"] = []
            for call in calls:
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                arguments = call.get("arguments") if isinstance(call, dict) else getattr(call, "arguments", None)
                if isinstance(call_id, str) and isinstance(name, str) and isinstance(arguments, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in arguments.items()):
                    entry["tool_calls"].append({"id": call_id, "name": name, "arguments": dict(arguments)})
    return entry


def initial_state(message_history=None) -> dict:
    """Restore recorded facts without issuing any historical tool call again."""
    history = []
    for message in message_history or ():
        tool_messages = message.get("tool_messages") if isinstance(message, dict) else getattr(message, "tool_messages", None)
        if tool_messages is not None:
            history.append({"role": "tools", "tool_messages": [_tool_entry(item) for item in tool_messages]})
        else:
            entry = _history_entry(message)
            if entry is not None:
                history.append(entry)
    state = {
        "schema_version": SCHEMA_VERSION,
        "turn": 0,
        "pending_call_id": None,  # Active t1 lookup ID; must match the sole pending_calls entry.
        "pending_calls": {},
        "customer_id": None,  # A user-supplied claim until a lookup succeeds.
        "identity": {"verified": False, "customer_id": None},
        "history": history,
        "tasks": [],
        "proposals": [],
        "operations": [],
        "handoff": {"status": "not_requested"},
        "tool_calls_since_user": 0,
    }
    index = 0
    while index < len(history):
        entry = history[index]
        index += 1
        if entry["role"] == "user":
            state["turn"] += 1
            finish_pending(state, "unknown")
            state["tool_calls_since_user"] = 0
            state["identity"] = {"verified": False, "customer_id": None}
            state["customer_id"] = find_customer_id(entry["content"]) or state["customer_id"]
        elif entry["role"] == "assistant":
            calls = entry.get("tool_calls", ())
            if "tool_call_ids" in entry:
                try:
                    if len(calls) != 1 or len(entry["tool_call_ids"]) != 1:
                        raise InvalidAction("Only one lookup may be outstanding")
                    call = calls[0]
                    record_lookup_call(state, ToolAction(id=call["id"], name=call["name"], arguments=call["arguments"]))
                except InvalidAction:
                    finish_pending(state, "unknown")
                    state["identity"] = {"verified": False, "customer_id": None}
        elif entry["role"] in {"tool", "tools"}:
            # Plain ToolMessages may describe one MultiToolMessage. Consecutive
            # results without an intervening assistant call are one batch.
            entries = entry["tool_messages"][:] if entry["role"] == "tools" else [entry]
            while index < len(history) and history[index]["role"] in {"tool", "tools"}:
                item = history[index]
                entries.extend(item["tool_messages"] if item["role"] == "tools" else [item])
                index += 1
            state["turn"] += 1
            outcomes = tuple(ToolOutcome(id=item["id"], content=item["content"], error=item["error"]) for item in entries)
            consume_lookup_results(state, outcomes)
    for entry in history:
        ids = entry.get("tool_call_ids", ()) if entry["role"] == "assistant" else (
            [item["id"] for item in entry["tool_messages"]] if entry["role"] == "tools" else (entry.get("id", ""),))
        for call_id in ids:
            match = re.fullmatch(r"lookup-(\d+)", call_id) if isinstance(call_id, str) else None
            if match:
                state["turn"] = max(state["turn"], int(match.group(1)))
    return clone_state(state)


def clone_state(state: dict) -> dict:
    """Round-trip the state to reject non-JSON values and avoid aliasing."""
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != SCHEMA_VERSION:
        raise InvalidState("Unsupported session state version")
    try:
        copied = json.loads(json.dumps(state, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvalidState("Session state must be JSON serializable") from exc
    if any(not isinstance(copied.get(key), list) for key in ("history", "tasks", "proposals", "operations")):
        raise InvalidState("Malformed session lists")
    if any(type(copied.get(key)) is not int or copied[key] < 0 for key in ("turn", "tool_calls_since_user")):
        raise InvalidState("Malformed session counters")
    identity, handoff = copied.get("identity"), copied.get("handoff")
    if not isinstance(identity, dict) or type(identity.get("verified")) is not bool or "customer_id" not in identity:
        raise InvalidState("Malformed identity")
    if not isinstance(handoff, dict) or not isinstance(handoff.get("status"), str):
        raise InvalidState("Malformed handoff")
    if "customer_id" not in copied or any(value is not None and (not isinstance(value, str) or not value) for value in (copied["customer_id"], identity["customer_id"])):
        raise InvalidState("Malformed customer ID")
    if identity["verified"] and not identity["customer_id"]:
        raise InvalidState("Verified identity requires a customer ID")
    if identity["verified"] and identity["customer_id"] != copied["customer_id"]:
        raise InvalidState("Verified identity must match the active customer")
    pending_id, pending = copied.get("pending_call_id"), copied.get("pending_calls")
    if "pending_call_id" not in copied or not isinstance(pending, dict):
        raise InvalidState("Malformed pending calls")
    if pending_id is not None and (not isinstance(pending_id, str) or not pending_id):
        raise InvalidState("Pending call ID must be nonempty")
    if set(pending) != ({pending_id} if pending_id is not None else set()):
        raise InvalidState("Inconsistent pending call slot")
    ids = set()
    for operation in copied["operations"]:
        if not isinstance(operation, dict) or not isinstance(operation.get("call_id"), str) or not operation["call_id"] or operation["call_id"] in ids:
            raise InvalidState("Invalid or repeated operation ID")
        if not isinstance(operation.get("name"), str) or type(operation.get("mutates")) is not bool or operation.get("status") not in {"sent", "succeeded", "failed", "unknown"}:
            raise InvalidState("Malformed operation")
        ids.add(operation["call_id"])
    sent_ids = {operation["call_id"] for operation in copied["operations"] if operation["status"] == "sent"}
    if sent_ids != set(pending):
        raise InvalidState("Pending calls must match sent operations")
    if pending_id is not None:
        item = pending[pending_id]
        if not isinstance(item, dict) or item.get("mutates") is not False:
            raise InvalidState("Malformed lookup descriptor")
        try:
            validate_tool_action(ToolAction(id=pending_id, name=item.get("name"), arguments=item.get("arguments")))
        except InvalidAction as exc:
            raise InvalidState("Invalid pending lookup") from exc
        operation = next(operation for operation in copied["operations"] if operation["call_id"] == pending_id)
        if operation["name"] != item["name"] or operation["mutates"] != item["mutates"]:
            raise InvalidState("Pending lookup must match its operation")
    return copied
