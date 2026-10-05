"""JSON-only session state; no SDK objects or module-global conversation data."""

import json
import re

from support_agent.domain.customer import find_customer_id
from support_agent.protocol import Decision, InvalidAction, ToolAction, ToolOutcome, validate_tool_action


# Introduction version stays fixed when later state schemas are added.
CANCELLATION_SCHEMA_VERSION = 8
HANDOFF_SCHEMA_VERSION = 9
SCHEMA_VERSION = HANDOFF_SCHEMA_VERSION


class InvalidState(ValueError):
    """Reject incomplete or inconsistent state at the session boundary."""


def quarantine_state(evidence, code):
    """Terminal platform envelope, never an alternate identity/session state.

    Retain serializable damaged evidence without repairing or granting access.
    Non-JSON evidence cannot be persisted; report that explicitly in the guard.
    """
    try:
        snapshot = json.loads(json.dumps(evidence, allow_nan=False))
        retained = True
    except (TypeError, ValueError):
        snapshot, retained = None, False
    return {"session_block": {"code": code, "evidence_retained": retained}, "quarantined_state": snapshot}


def finish_pending(state: dict, status: str) -> None:
    ids = set(state["pending_calls"])
    for operation in state["operations"]:
        if operation["call_id"] in ids and operation["status"] == "sent":
            operation["status"] = status
    state["pending_calls"].clear()
    state["pending_call_id"] = None


def result_history(outcomes, *, status="succeeded") -> dict:
    """Keep accepted facts; rejected batches retain only IDs and bounded status.

    Mismatch keeps error=False so replay still classifies it as unknown rather
    than a transport failure. Rejected batches retain no partial facts.
    """
    if status not in {"succeeded", "failed", "mismatch", "unknown", "none"}:
        raise ValueError("Unknown read result status")
    safe_content = json.dumps({"read_result_status": status})
    entries = [{"role": "tool", "id": result.id,
                "content": result.content if status == "succeeded" and not result.error else safe_content,
                "error": True if status == "failed" else result.error} for result in outcomes]
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
        if isinstance(message, dict):
            for key in ("proposal", "proposal_ack", "proposal_set", "proposal_set_ack", "task_plan", "write_event",
                        "presentation_note", "address_dispatch", "address_result", "address_unknown", "address_abandoned", "address_assessment",
                        "payment_dispatch", "payment_result", "payment_unknown", "payment_abandoned", "payment_assessment",
                        "cancellation_dispatch", "cancellation_result", "cancellation_unknown", "cancellation_abandoned", "cancellation_assessment", "handoff_event", "handoff_assessment"):
                if key in message:
                    entry[key] = message[key]
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
        "pending_call_id": None,  # Sole pending read ID; None for empty or multi-call batches.
        "pending_calls": {},
        "customer_id": None,  # A user-supplied claim until a lookup succeeds.
        "identity": {"verified": False, "customer_id": None},
        "history": [],  # Only preceding messages may authorize a restored call.
        "tasks": [],
        "proposals": [],
        "operations": [],
        "handoff": {"status": "not_requested"},
        "tool_calls_since_user": 0,
        "model_calls_since_user": 0,
        "identity_evidence": None,
        "customer_record": None,
        "user_request": "",
        "model_usage": [],
        "verification_draft": {},
        "address_pending": None,
        "payment_pending": None,
        "cancellation_pending": None,
    }
    index = 0
    while index < len(history):
        entry = history[index]
        index += 1
        if entry["role"] not in {"tool", "tools"}:
            state["history"].append(entry)
        if entry["role"] == "user":
            state["turn"] += 1
            finish_pending(state, "unknown")
            state["tool_calls_since_user"] = 0
            state["model_calls_since_user"] = 0
            state["user_request"] = entry["content"]
            from support_agent.proposals import observe_user
            observe_user(state, len(state["history"]) - 1)
            from support_agent.domain.identity import fields_from_text
            fields = fields_from_text(entry["content"])
            if not state["identity"]["verified"] and fields:
                if "email" in fields:
                    state["verification_draft"] = {"email": fields["email"]}
                else:
                    state["verification_draft"].pop("email", None)
                    state["verification_draft"].update(fields)
            if not state["identity"]["verified"]:
                state["customer_id"] = find_customer_id(entry["content"]) or state["customer_id"]
        elif entry["role"] == "assistant":
            if "handoff_event" in entry:
                from support_agent.handoff_session import restore_handoff
                restore_handoff(state, len(state["history"]) - 1)
            elif {"cancellation_dispatch", "cancellation_result", "cancellation_unknown", "cancellation_abandoned"} & set(entry):
                from support_agent.cancellation_session import restore_cancellation_control
                restore_cancellation_control(state, len(state["history"]) - 1)
            elif {"payment_dispatch", "payment_result", "payment_unknown", "payment_abandoned"} & set(entry):
                from support_agent.payment_session import restore_payment_control
                restore_payment_control(state, len(state["history"]) - 1)
            elif {"address_dispatch", "address_result", "address_unknown", "address_abandoned"} & set(entry):
                from support_agent.address_session import restore_address_control
                restore_address_control(state, len(state["history"]) - 1)
            elif "write_event" in entry:
                from support_agent.write_session import restore_write_event
                restore_write_event(state, len(state["history"]) - 1)
            elif "task_plan" in entry:
                from support_agent.tasks import restore_task_plan
                restore_task_plan(state, len(state["history"]) - 1)
            elif "proposal" in entry:
                from support_agent.proposals import restore_presentation
                restore_presentation(state, len(state["history"]) - 1)
            elif "proposal_ack" in entry:
                from support_agent.proposals import restore_ack
                restore_ack(state, len(state["history"]) - 1)
            elif "proposal_set" in entry:
                from support_agent.proposals import restore_proposal_set
                restore_proposal_set(state, len(state["history"]) - 1)
            elif "proposal_set_ack" in entry:
                from support_agent.proposals import restore_set_ack
                restore_set_ack(state, len(state["history"]) - 1)
            calls = entry.get("tool_calls", ())
            if "tool_call_ids" in entry:
                try:
                    from support_agent.read_session import record_calls
                    actions = tuple(ToolAction(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in calls)
                    if len(calls) != len(entry["tool_call_ids"]):
                        raise InvalidAction("Incomplete historical calls")
                    Decision(calls=actions)
                    record_calls(state, actions)
                except (InvalidAction, ValueError):
                    finish_pending(state, "unknown")
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
            from support_agent.read_session import consume_results
            status, _ = consume_results(state, outcomes)
            state["history"].append(result_history(outcomes, status=status))
    for entry in history:
        ids = entry.get("tool_call_ids", ()) if entry["role"] == "assistant" else (
            [item["id"] for item in entry["tool_messages"]] if entry["role"] == "tools" else (entry.get("id", ""),))
        for call_id in ids:
            match = re.fullmatch(r"(?:lookup|read)-(\d+)", call_id) if isinstance(call_id, str) else None
            if match:
                state["turn"] = max(state["turn"], int(match.group(1)))
    return clone_state(state)


def clone_state(state: dict) -> dict:
    """Round-trip the state to reject non-JSON values and avoid aliasing."""
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] not in {1, 2, 3, 4, 5, 6, 7, 8, SCHEMA_VERSION}:
        raise InvalidState("Unsupported session state version")
    if {"write_authorized", "delivery_verified", "confirmed", "condition_verified"} & set(state):
        raise InvalidState("Authorization flags cannot be added to session state")
    try:
        copied = json.loads(json.dumps(state, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvalidState("Session state must be JSON serializable") from exc
    if copied["schema_version"] < HANDOFF_SCHEMA_VERSION:
        if (copied.get("handoff") != {"status": "not_requested"} or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and {"handoff_event", "handoff_assessment"} & set(e) for e in copied["history"])):
            raise InvalidState("Legacy state cannot contain schema 9 transfer evidence")
    if copied["schema_version"] < CANCELLATION_SCHEMA_VERSION:
        if (copied.get("cancellation_pending") is not None or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and {"cancellation_dispatch", "cancellation_result", "cancellation_unknown", "cancellation_abandoned", "cancellation_assessment"} & set(e) for e in copied["history"])):
            raise InvalidState("Legacy state cannot contain schema 8 cancellation workflow evidence")
        copied["cancellation_pending"] = None
    if copied["schema_version"] < 7:
        if (copied.get("payment_pending") is not None or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and {"payment_dispatch", "payment_result", "payment_unknown", "payment_abandoned", "payment_assessment"} & set(e) for e in copied["history"])):
            raise InvalidState("Legacy state cannot contain schema 7 payment workflow evidence")
        copied["payment_pending"] = None
    if copied["schema_version"] < 6:
        if (copied.get("address_pending") is not None or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and {"presentation_note", "address_dispatch", "address_result", "address_unknown", "address_abandoned", "address_assessment"} & set(e)
                       for e in copied["history"])):
            raise InvalidState("Legacy state cannot contain schema 6 address workflow evidence")
        copied["address_pending"] = None
    if copied["schema_version"] < 5:
        if (not isinstance(copied.get("history"), list) or not isinstance(copied.get("operations"), list)
                or any(isinstance(e, dict) and "write_event" in e for e in copied["history"])
                or any(isinstance(o, dict) and o.get("mutates") is not False for o in copied["operations"])):
            raise InvalidState("Legacy state cannot contain schema 5 write evidence")
    if copied["schema_version"] < 4:
        if (copied.get("tasks") != [] or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and "task_plan" in e for e in copied["history"])):
            raise InvalidState("Legacy state cannot contain schema 4 task evidence")
    if copied["schema_version"] == 1:
        if (copied.get("proposals") != [] or not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and ({"proposal", "proposal_ack", "proposal_set", "proposal_set_ack"} & set(e)) for e in copied["history"])):
            raise InvalidState("Legacy state has no supported proposal evidence schema")
        copied["schema_version"] = SCHEMA_VERSION
    elif copied["schema_version"] == 2:
        if (not isinstance(copied.get("history"), list)
                or any(isinstance(e, dict) and ({"proposal_set", "proposal_set_ack"} & set(e)) for e in copied["history"])):
            raise InvalidState("Schema 2 cannot contain schema 3 scope evidence")
        copied["schema_version"] = SCHEMA_VERSION
    elif copied["schema_version"] in {3, 4, 5, 6, 7, 8}:
        copied["schema_version"] = SCHEMA_VERSION
    # M1 states remain readable; missing evidence does not grant private reads.
    for key, default in (("model_calls_since_user", 0), ("identity_evidence", None), ("customer_record", None), ("user_request", ""), ("model_usage", []), ("verification_draft", {})):
        copied.setdefault(key, default)
    if any(not isinstance(copied.get(key), list) for key in ("history", "tasks", "proposals", "operations")):
        raise InvalidState("Malformed session lists")
    for entry in copied["history"]:
        if not isinstance(entry, dict) or entry.get("role") not in {"user", "assistant", "tool", "tools"}:
            raise InvalidState("Malformed session history")
        if entry["role"] != "tools" and not isinstance(entry.get("content"), str):
            raise InvalidState("History content must be text")
        if entry["role"] == "tools":
            batch = entry.get("tool_messages")
            if not isinstance(batch, list) or any(not isinstance(r, dict) or not isinstance(r.get("content"), str) for r in batch):
                raise InvalidState("Malformed history result batch")
        if len({"proposal", "proposal_ack", "proposal_set", "proposal_set_ack", "task_plan", "write_event",
                "address_dispatch", "address_result", "address_unknown", "address_abandoned",
                "payment_dispatch", "payment_result", "payment_unknown", "payment_abandoned",
                "cancellation_dispatch", "cancellation_result", "cancellation_unknown", "cancellation_abandoned", "handoff_event"} & set(entry)) > 1:
            raise InvalidState("Mixed presentation/acknowledgement evidence")
        if len({"address_assessment", "payment_assessment", "cancellation_assessment", "handoff_assessment"} & set(entry)) > 1:
            raise InvalidState("Mixed workflow diagnostics")
        if "presentation_note" in entry and "proposal_set" not in entry:
            raise InvalidState("Presentation notes require a complete operation set")
    if any(type(copied.get(key)) is not int or copied[key] < 0 for key in ("turn", "tool_calls_since_user", "model_calls_since_user")):
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
    if len(pending) > 8 or pending_id != (next(iter(pending)) if len(pending) == 1 else None):
        raise InvalidState("Inconsistent pending call slot")
    ids = set()
    for operation in copied["operations"]:
        if not isinstance(operation, dict) or not isinstance(operation.get("call_id"), str) or not operation["call_id"] or operation["call_id"] in ids:
            raise InvalidState("Invalid or repeated operation ID")
        statuses = {"sent", "succeeded", "failed", "unknown"} | ({"acknowledged"} if operation.get("mutates") is True else set())
        if not isinstance(operation.get("name"), str) or type(operation.get("mutates")) is not bool or operation.get("status") not in statuses:
            raise InvalidState("Malformed operation")
        if not operation["mutates"] and set(operation) != {"call_id", "name", "mutates", "status"}:
            raise InvalidState("Read operations cannot carry unvalidated receipt or authorization fields")
        ids.add(operation["call_id"])
    sent_ids = {operation["call_id"] for operation in copied["operations"] if not operation["mutates"] and operation["status"] == "sent"}
    if sent_ids != set(pending):
        raise InvalidState("Pending calls must match sent operations")
    if not isinstance(copied["user_request"], str):
        raise InvalidState("Invalid current request")
    if not isinstance(copied["model_usage"], list):
        raise InvalidState("Invalid model usage records")
    draft = copied["verification_draft"]
    if not isinstance(draft, dict) or set(draft) - {"email", "first_name", "last_name", "postal_code"} or any(not isinstance(v, str) for v in draft.values()):
        raise InvalidState("Invalid independent verification draft")
    evidence, record = copied["identity_evidence"], copied["customer_record"]
    if evidence is not None:
        from support_agent.domain.identity import PROOF_FIELDS, matches_session_customer, supplied_by_user
        if (not isinstance(evidence, dict) or set(evidence) != {"inputs", "verified_at_turn", "source"}
                or not isinstance(evidence["inputs"], dict) or set(evidence["inputs"]) != set(PROOF_FIELDS)
                or type(evidence["verified_at_turn"]) is not int or not 0 <= evidence["verified_at_turn"] <= copied["turn"]
                or evidence["source"] != "user_input_and_matched_search_profile"
                or not identity["verified"] or not supplied_by_user(evidence["inputs"], copied["history"])
                or not matches_session_customer(record, evidence["inputs"], identity["customer_id"], copied["history"])):
            raise InvalidState("Invalid independent identity evidence")
    elif record is not None:
        raise InvalidState("Customer record requires identity evidence")
    for pending_id, item in pending.items():
        if not isinstance(item, dict) or item.get("mutates") is not False:
            raise InvalidState("Malformed lookup descriptor")
        try:
            validate_tool_action(ToolAction(id=pending_id, name=item.get("name"), arguments=item.get("arguments")))
            from support_agent.read_session import bind_arguments
            bind_arguments(item["name"], item["arguments"], copied)
        except InvalidAction as exc:
            raise InvalidState("Invalid pending lookup") from exc
        operation = next(operation for operation in copied["operations"] if operation["call_id"] == pending_id)
        if operation["name"] != item["name"] or operation["mutates"] != item["mutates"]:
            raise InvalidState("Pending lookup must match its operation")
    from support_agent.proposals import validate_ledger
    try:
        validate_ledger(copied)
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidState("Invalid proposal or confirmation evidence") from exc
    from support_agent.tasks import validate_tasks
    try:
        validate_tasks(copied)
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidState("Invalid task plan evidence") from exc
    from support_agent.write_session import validate_write_operations
    try:
        validate_write_operations(copied)
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidState("Invalid write lifecycle evidence") from exc
    if any(kind + "_pending" not in copied for kind in ("address", "payment", "cancellation")):
        raise InvalidState("Missing workflow pending slot")
    from support_agent.workflow_boundary import validate_workflows
    try:
        validate_workflows(copied)
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidState("Invalid workflow evidence") from exc
    from support_agent.handoff_session import validate_handoff
    try:
        validate_handoff(copied)
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidState("Invalid human transfer evidence") from exc
    return copied
