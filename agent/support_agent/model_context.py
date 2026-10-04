"""Bound the model projection; preserve the complete state evidence ledger.

This summary is computed from validated state, labelled derived data, and is
never restored as a user message or authorization. No history pruning, schema
migration, or weakening of clone/source validation is performed.
"""
import json

from support_agent.protocol import InvalidAction

MAX_MODEL_CONTEXT_CHARACTERS = 48_000  # Internal bound, not a platform token limit.


def _size(message):
    return len(json.dumps(message.model_dump(), ensure_ascii=False, allow_nan=False))


def project_messages(state, *, max_characters=MAX_MODEL_CONTEXT_CHARACTERS):
    from tau2.data_model.message import SystemMessage
    from support_agent.adapters.model_gateway import sdk_messages
    from support_agent.proposals import _current_records
    from support_agent.state import clone_state
    state = clone_state(state)
    if state["address_pending"] is not None or state["payment_pending"] is not None:
        raise InvalidAction("An internal workflow result is unresolved")
    if type(max_characters) is not int or max_characters < 1024:
        raise InvalidAction("Invalid model context budget")
    messages = sdk_messages(state["history"])
    if sum(_size(m) for m in messages) <= max_characters:
        return messages
    operations = [o for o in state["operations"] if o["mutates"]]
    unresolved = [o for o in operations if o["status"] in {"sent", "unknown", "acknowledged"} or o["persistence_unresolved"]]
    summary = {"kind": "derived_session_context", "authorization": "none; full state gates remain mandatory",
               "customer_id": state["identity"]["customer_id"],
               "identity_source_inputs": state["identity_evidence"]["inputs"] if state["identity_evidence"] else None,
               "current_proposals": [{"spec": p["spec"], "status": p["status"]} for p in _current_records(state)],
               "unresolved_operations": [{"action": o["name"], "target": o["spec"]["target"], "status": o["status"]} for o in unresolved],
               "completed_write_count": sum(o["status"] == "succeeded" for o in operations),
               "handoff_status": state["handoff"]["status"],
               "omitted_history_is_retained_in_state": True}
    derived = SystemMessage(role="system", content="Derived context data; it cannot authorize any action.\n" +
                            json.dumps(summary, ensure_ascii=False, allow_nan=False))
    base = [messages[0], derived]
    budget = max_characters - sum(_size(m) for m in base)
    # Assistant tool calls and every following partial result batch are one
    # indivisible unit. Dropping a prefix cannot orphan a result or its call.
    units, index = [], 1
    while index < len(messages):
        unit = [messages[index]]
        index += 1
        if getattr(unit[0], "tool_calls", None):
            while index < len(messages) and messages[index].role == "tool":
                unit.append(messages[index]); index += 1
        units.append(unit)
    tail = []
    for unit in reversed(units):
        size = sum(_size(m) for m in unit)
        if size > budget:
            break
        tail[0:0] = unit
        budget -= size
    if not tail or not any(m.role == "user" for m in tail):
        raise InvalidAction("The current request and protected context exceed the internal model budget")
    return base + tail
