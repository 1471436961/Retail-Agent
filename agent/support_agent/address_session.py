"""M4.1 address producer and replayable toolkit boundary.

The model cannot dispatch this tool. Its snapshot carries the same original
user/identity/proposal/journal chain; it is not a signature of host history.
Only the toolkit owns the trusted Client API and shared in-process claim store.
"""
import json
import re
from copy import deepcopy

from support_agent.domain.addresses import (address_fields, complete_address,
                                          request_from_history, starts_address_request)
from support_agent.domain.orders import order_state_rule
from support_agent.protocol import InvalidAction
from support_agent.workflow_limits import (WorkflowResultTooLarge, MAX_WORKFLOW_RESULT_BYTES,
                                         json_bytes)

ADDRESS_TOOL = "address_workflow"
ADDRESS_ACTIONS = frozenset({"shipping_address", "default_shipping_address"})


def _boundary():
    from support_agent.workflow_boundary import WorkflowBoundary
    return WorkflowBoundary("address", MAX_WORKFLOW_RESULT_BYTES)


def _tag(decision, state, code, **details):
    return _boundary().tag(decision, state, code, **details)


def _reply(state, code, text, **details):
    return _boundary().reply(state, code, text, **details)


def _event(state, key, data):
    return _boundary().event(state, key, data)


def restore_address_control(state, index):
    return _boundary().restore(state, index)


def validate_address_control(state):
    return _boundary().validate(state)


def dispatch_address(state, mode):
    return _boundary().dispatch(state, mode)


def route_address(state, text=None):
    """Called after ordinary identity and consent observation, before ACK text."""
    from support_agent.proposals import _current_records
    if state["address_pending"] is not None:
        if state["address_pending"]["mode"] == "prepare" and text is not None:
            # An actual user turn can safely abandon only read-only work. Late
            # results cannot overwrite this turn or a subsequently new dispatch.
            _event(state, "address_abandoned", {"call_id": state["address_pending"]["call_id"]})
        else:
            return _reply(state, "address_workflow_unresolved", "The address workflow outcome is unresolved. I will not send another address operation or claim completion.")
    from support_agent.domain.cancellation_intake import starts_cancellation_request
    if text is not None and starts_cancellation_request(text):
        return None
    request = request_from_history(state["history"])
    if request is None:
        return None
    from support_agent.domain.payment_intake import request_from_history as payment_request
    payment = payment_request(state["history"])
    if payment is not None and payment["request_index"] > request["request_index"]:
        return None
    from support_agent.domain.cancellation_intake import request_from_history as cancellation_request
    cancellation = cancellation_request(state["history"])
    if cancellation is not None and cancellation["request_index"] > request["request_index"]:
        return None
    current = _current_records(state)
    attempted = {o["version"] for o in state["operations"] if o["mutates"]}
    if any(p["spec"]["action"] not in ADDRESS_ACTIONS and p["version"] not in attempted for p in current):
        # Preserve the shared scope parser's amendment/condition explanation.
        # A foreign proposal is not an address intake, and its unfinished plan
        # is also protected by _prepare before any new proposal is presented.
        return None
    confirmed = [p for p in current if p["status"] == "confirmed" and p["version"] not in attempted]
    latest = next((e["content"] for e in reversed(state["history"]) if e["role"] == "user"), "")
    fields, _, error = address_fields(latest)
    request_message = starts_address_request(latest) or bool(fields or error)
    if text is not None and re.search(r"\b(retry|try again)\b|重试|重新准备", text, re.I):
        return dispatch_address(state, "prepare")  # Re-read/recap; never consent.
    # An unrelated later user turn cannot spend retained consent automatically.
    latest_index = max(i for i, e in enumerate(state["history"]) if e["role"] == "user")
    fresh_assent = any(p["confirmation"] and p["confirmation"]["history_index"] == latest_index for p in confirmed)
    if confirmed and fresh_assent and not request_message:
        return dispatch_address(state, "execute")
    if text is not None and request_message:
        return dispatch_address(state, "prepare")
    # Continue an intake that started before verification, or an explicit order
    # ID clarification. Tool result processing never manufactures user consent.
    if text is None or request["request_index"] == latest_index:
        if not current or request_message:
            return dispatch_address(state, "prepare")
    return None


def accept_address_result(state, outcomes):
    return _boundary().accept(state, outcomes)


def _accepted_bodies(history, names):
    calls, bodies = {}, []
    for entry in history:
        for call in entry.get("tool_calls", []) if entry["role"] == "assistant" else []:
            calls[call["id"]] = call["name"]
        results = entry.get("tool_messages", []) if entry["role"] == "tools" else [entry] if entry["role"] == "tool" else []
        for item in results:
            if not item.get("error") and calls.get(item["id"]) in names:
                body = json.loads(item["content"])
                if "read_result_status" not in body:
                    bodies.append(body)
    return bodies


def _safe_read(state, api, name, selectors):
    from support_agent.write_session import _read
    try:
        return _read(state, api, name, selectors, "address-intake")
    except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
        # Read-only failure: close any registered read batch with safe failure
        # evidence, never retain transport text or manufacture accepted facts.
        from support_agent.protocol import ToolOutcome
        from support_agent.read_session import consume_results
        from support_agent.state import result_history
        if state["pending_calls"]:
            outcomes = tuple(ToolOutcome(i, "", True) for i in state["pending_calls"])
            status, _ = consume_results(state, outcomes)
            state["history"].append(result_history(outcomes, status=status))
        return None, "failed"


def _prepare(state, api, *, notice="", prior_records=()):
    from support_agent.adapters.read_api import customer_order_ids
    from support_agent.proposals import normalize_spec, present_proposals
    from support_agent.tasks import present_task_plan
    request = request_from_history(state["history"])
    messages = {"target_order_required": "Please provide the exact order ID whose shipping address should change.",
                "address_record_required": "Should I change your profile default address, a specific order's address, or both?",
                "mixed_business_request": "This stage supports address changes. Other requested operations need a separate workflow; please clarify the address targets first.",
                "conditional_address_request": "The address request has an unresolved condition or sequence. Please clarify it and provide a new explicit address request; no update has been sent."}
    if request is None or request["error"]:
        code = request["error"] if request else "address_request_required"
        return _reply(state, code, messages.get(code, "Please provide supported address fields and a clear target record. No address has been changed."))
    if state["tool_calls_since_user"] >= 12:
        return _reply(state, "address_read_budget_exceeded", "The address read budget is exhausted. No additional address operation was sent.")
    _, status = _safe_read(state, api, "read_customer_profile", {})
    if status != "succeeded":
        return _reply(state, "address_profile_read_failed", "I could not refresh your profile. No address change has been prepared or sent.")
    own = customer_order_ids(state["customer_record"])
    source_id = request["source"].get("order_id")
    targets = [i for i in own if i != source_id] if request["all_orders"] else request["order_ids"][:]
    required = list(dict.fromkeys([*targets, *([source_id] if source_id else [])]))
    if any(order_id not in own for order_id in required):
        return _reply(state, "address_order_not_owned", "The address target or reference order is outside your verified order references. No order detail or write was requested.", decision_kind="deny")
    if len(targets) + int(request["default"]) > 8 or state["tool_calls_since_user"] + len(required) > 12:
        return _reply(state, "address_scope_budget_exceeded", "Please select a smaller set of address targets so every required read and confirmation can remain complete.")
    orders = {}
    for order_id in required:
        _, status = _safe_read(state, api, "get_order", {"order_id": order_id})
        if status != "succeeded":
            return _reply(state, "address_order_read_failed", "A required owned order could not be refreshed. No address change was sent; please resolve that read first.")
        orders[order_id] = _accepted_bodies(state["history"], {"get_order"})[-1]
    kind = request["source"]["kind"]
    shared = None
    if kind == "order":
        shared = orders[source_id].get("shipping_address")
    elif kind == "default":
        shared = state["customer_record"].get("default_shipping_address")
    elif kind == "original_default":
        profiles = _accepted_bodies(state["history"], {"lookup_customer", "verify_customer", "read_customer_profile"})
        shared = profiles[0].get("default_shipping_address") if profiles else None
    specs, notes, missing, records = [], [notice] if notice else [], [], []
    for action, order_id in ([*(('shipping_address', i) for i in targets),
                             *((('default_shipping_address', None),) if request["default"] else ())]):
        order = orders.get(order_id)
        target = {"customer_id": state["identity"]["customer_id"]}
        if order_id is not None:
            target["order_id"] = order_id
        diagnostic = {"action": action, "target": target}
        if order is not None and order_state_rule(order, action)["decision"] != "allow":
            records.append({**diagnostic, "decision": "deny", "code": "address_state_not_allowed", "status": order["status"]})
            if not request["all_orders"]:
                notes.append(f"Order {order_id}: shipping address cannot be changed in status {order['status']}. No change will be sent for this record.")
            continue
        base = shared if kind != "record" else (order.get("shipping_address") if order is not None else state["customer_record"].get("default_shipping_address"))
        if not request["fields"] and kind == "record":
            missing.append("new address fields")
            records.append({**diagnostic, "decision": "needs_information", "code": "address_fields_required"})
            continue
        params, needed = complete_address(base, request)
        missing.extend(needed)
        if needed:
            records.append({**diagnostic, "decision": "needs_information", "code": "address_fields_required"})
            continue
        if any(o["mutates"] and o["spec"]["target"] == target
               and (o["status"] in {"sent", "unknown", "acknowledged"} or o["persistence_unresolved"])
               for o in state["operations"]):
            notes.append(f"{'Order ' + order_id if order_id else 'Profile default address'}: an earlier update remains unresolved. A matching current address does not prove that update succeeded; no new write will be sent for this record.")
            records.append({**diagnostic, "decision": "needs_information", "code": "write_result_unresolved"})
            continue
        current = order.get("shipping_address") if order is not None else state["customer_record"].get("default_shipping_address")
        comparable = {**(current or {}), "address_line_2": (current or {}).get("address_line_2")}
        if params == comparable:
            notes.append(f"{'Order ' + order_id if order_id else 'Profile default address'}: the recorded address already matches; no update is needed.")
            records.append({**diagnostic, "decision": "allow", "code": "address_unchanged"})
            continue
        specs.append(normalize_spec({"action": action, "target": target, "parameters": params, "amount": {"kind": "not_applicable"}}))
        records.append({**diagnostic, "decision": "needs_information", "code": "address_recapped"})
    if missing:
        return _reply(state, "address_fields_required", "Please provide the missing address information: " + ", ".join(dict.fromkeys(missing)) + ". I will read back the complete address before any update.", records=records, missing_fields=list(dict.fromkeys(missing)))
    if not specs:
        codes = {r["code"] for r in records}
        code = next(iter(codes)) if len(codes) == 1 else "address_targets_assessed"
        kind = "deny" if records and all(r["decision"] == "deny" for r in records) else "allow" if records and all(r["code"] == "address_unchanged" for r in records) else "needs_information"
        return _reply(state, code, "\n".join(notes) or "There are no eligible pending address targets to update. No address has been changed.", decision_kind=kind, records=records)
    from support_agent.workflow_boundary import unfinished_other_tasks
    if unfinished_other_tasks(state, ADDRESS_ACTIONS):
        return _reply(state, "address_mixed_plan_requires_review", "An existing mixed operation plan needs clarification before replacing it with address tasks. No existing task has been discarded.")
    _, state = present_task_plan(state, [{"action": s["action"], "target": s["target"]} for s in specs])
    decision, state = present_proposals(state, specs, presentation_note="\n".join(notes))
    return _tag(decision, state, "address_confirmation_required", records=records, prior_records=list(prior_records))


def run_address_workflow(state, api, claims):
    from support_agent.state import clone_state
    from support_agent.proposals import _current_records
    from support_agent.adapters.write_runtime import SessionWriteRuntime
    from support_agent.write_session import execute_operation
    state = clone_state(state)
    original = deepcopy(state)
    pending = state["address_pending"]
    if (pending is None or pending["status"] != "pending" or len(state["history"]) != pending["index"] + 1
            or not state["identity"]["verified"] or not state["identity_evidence"] or state["cancellation_pending"] is not None or state["payment_pending"] is not None or state["pending_calls"]
            or state["handoff"]["status"] not in {"not_requested", "rejected"}):
        raise ValueError("An original idle verified dispatch is required")
    if pending["mode"] == "prepare":
        _event(state, "address_result", {"call_id": pending["call_id"]})
        try:
            decision, state = _prepare(state, api)
        except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
            state = deepcopy(original)
            _event(state, "address_result", {"call_id": pending["call_id"]})
            decision, state = _reply(state, "address_preparation_failed", "Address preparation could not complete safely. No business write was sent; please clarify or retry preparation.")
    else:
        attempted = {o["version"] for o in state["operations"] if o["mutates"]}
        selected = [p for p in _current_records(state) if p["status"] == "confirmed" and p["version"] not in attempted]
        if not selected or any(p["spec"]["action"] not in ADDRESS_ACTIONS for p in selected):
            raise ValueError("Only confirmed current complete address operations can be submitted")
        # Independent order records before the profile; changing the default
        # profile last avoids invalidating order facts within this confirmed set.
        selected.sort(key=lambda p: p["spec"]["action"] == "default_shipping_address")
        try:
            runtime = SessionWriteRuntime(api, claims=claims)
        except (TypeError, ValueError, RuntimeError):
            _event(state, "address_result", {"call_id": pending["call_id"]})
            decision, state = _reply(state, "address_runtime_unavailable", "The trusted address runtime is unavailable. No address write was sent.")
            return _payload(decision, state, original, pending)
        lines, records, refresh_needed, uncertain = [], [], False, False
        for record in selected:
            spec = deepcopy(record["spec"])
            try:
                result, state = execute_operation(state, record["version"], spec, runtime)
            except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
                # A raised operation may have sent from its private cloned state.
                # Preserve earlier returned journals; do not invent this outcome
                # or proceed with later records. The original batch stays Unknown.
                result = {"decision": "needs_information", "code": "address_operation_uncertain"}
                uncertain = True
            records.append({"action": spec["action"], "target": spec["target"], "version": record["version"],
                            "decision": result["decision"], "code": result["code"]})
            target = "Order " + spec["target"]["order_id"] if "order_id" in spec["target"] else "Profile default address"
            if result["code"] == "write_verified":
                lines.append(target + ": address update accepted and independently verified. " + json.dumps(spec["parameters"], ensure_ascii=False))
            elif result["code"] == "write_rejected":
                lines.append(target + ": update rejected; it was not retried.")
            else:
                refresh_needed = refresh_needed or result["code"] == "facts_changed"
                lines.append(target + ": update not verified (" + result["code"] + "). I will not report completion or repeat an uncertain operation; changed facts require a new complete recap and confirmation.")
            if uncertain:
                break
        _event(state, "address_unknown" if uncertain else "address_result", {"call_id": pending["call_id"]})
        if refresh_needed and not uncertain:
            try:
                decision, state = _prepare(state, api, notice="\n".join(lines), prior_records=records)
            except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
                decision, state = _reply(state, "address_repreparation_failed", "\n".join(lines) + "\nA new complete recap could not be prepared; no additional write was sent.", records=records)
        else:
            code = "address_execution_uncertain" if uncertain else "address_updates_verified" if all(r["code"] == "write_verified" for r in records) else "address_results_mixed" if len({r["code"] for r in records}) > 1 else records[0]["code"]
            decision, state = _reply(state, code, "\n".join(lines), records=records,
                                     decision_kind="allow" if code == "address_updates_verified" else "needs_information")
    return _payload(decision, state, original, pending)


def _payload(decision, state, original, pending):
    from support_agent.state import clone_state
    payload = {"reply": decision.text, "state": clone_state(state), "assessment": state["history"][-1]["address_assessment"]}
    if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES:
        return payload
    if pending["mode"] == "prepare":
        state = deepcopy(original)
        _event(state, "address_result", {"call_id": pending["call_id"]})
        decision, state = _reply(state, "address_result_budget_exceeded", "The read-only preparation result exceeds the tool transport budget. No business write was sent; the full identity and prior journal were preserved without trimming.")
        payload = {"reply": decision.text, "state": clone_state(state), "assessment": state["history"][-1]["address_assessment"]}
        if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES:
            return payload
    # Do not truncate a post-send journal or turn delivery failure into a business
    # rejection. Host result validation reserves execution Unknown and no retry.
    raise WorkflowResultTooLarge("Address outcome cannot be delivered within the internal result budget")
