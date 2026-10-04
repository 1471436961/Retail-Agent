"""M3.5 internal refresh and single-send lifecycle; no model WRITE tools.

The default runtime is absent. A concrete runtime must establish authentic
submission/consent provenance, business parameters and durable checkpoints.
JSON history is evidence within that trust boundary, not a signed transcript.
There is deliberately no automatic retry or executable classroom write adapter.
"""
import json
import hashlib

from support_agent.adapters import read_api
from support_agent.adapters.client_api import ClientAPIError
from support_agent.domain.write_receipts import fulfillment_rule, normalize_receipt, receipt_matches_readback
from support_agent.domain.money import price_difference
from support_agent.domain.policies import settlement_method_rule
from support_agent.domain.rules import allow, deny, need
from support_agent.protocol import Decision, ToolAction, ToolOutcome
from support_agent.proposals import (InvalidProposal, _clean_read_history, _current_records,
                                     _scope_facts, check_confirmation, normalize_spec)
from support_agent.read_session import bind_arguments, consume_results, record_decision
from support_agent.state import InvalidState, clone_state, initial_state, result_history


class InvalidWrite(ValueError):
    pass


class WriteClaimConflict(ValueError):
    """The trusted durable runtime already claimed this send/record."""


class WriteRuntime:
    """Trusted integration port, instance-local and never deserialized from state.

    M4/M5 must supply concrete business validation and send adapters. The
    base port stays disabled. SessionWriteRuntime implements the documented
    sequential session scope. Arbitrary worker/restart durability is a stronger
    deployment requirement, not a prerequisite invented for classroom use.
    claim_sent must return exactly True on success; rejection raises
    WriteClaimConflict, or any other return blocks sending. call_id locates a
    journal entry only: deduplicate claim_identity within the trusted conversation
    and reject unresolved record claims or regressed snapshots.
    """
    def __init__(self, client_api):
        self.client_api = client_api

    def assess_submission(self, state, version, spec):
        return need("submission_contract_required", "Authentic message/state submission and durable consent evidence must be established.", "CF-01", "EN-02")

    def assess_business(self, state, spec):
        return need("business_validation_required", "A business producer must verify complete parameters, quote, payment and destination rules.", "MO-01")

    def checkpoint(self, state):
        raise NotImplementedError("Durable sent-state persistence is required")

    def claim_sent(self, state, call_id):
        raise NotImplementedError("Atomic durable send claim is required")

    def send(self, spec):
        raise NotImplementedError("No classroom business write adapter is enabled")


def _result(code, message, *, decision="needs_information", **details):
    fn = {"allow": allow, "deny": deny, "needs_information": need}[decision]
    return fn(code, message, "CF-01", "CF-02", "EN-01", details={**details, "write_authorized": False})


def _closed(result):
    return {**result, "details": {**result["details"], "write_authorized": False}}


def claim_identity(state, call_id):
    """Stable logical identity; the runtime supplies the trusted session scope.

    History position and spec edits cannot create a second identity for the same
    version/record. Different backend sessions use separate claim stores.
    """
    op = next(o for o in state["operations"] if o["mutates"] and o["call_id"] == call_id)
    value = {"version": op["version"], "target": op["spec"]["target"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write_block(state, version, spec):
    for op in state["operations"]:
        if not op["mutates"]:
            continue
        if op["version"] == version:
            return _result("write_already_attempted", "This version has already entered the send lifecycle; it cannot be sent again.")
        if op["spec"]["target"] == spec["target"] and (op["status"] in {"sent", "unknown", "acknowledged"} or op["persistence_unresolved"]):
            return _result("write_result_unresolved", "An earlier write on this record is unresolved; investigate without retrying.")
    return None


def _task_block(state, spec, *, prior_writes=None):
    from support_agent.tasks import inspect_task_plan
    if not state["tasks"]:
        return None
    node = next((n for n in state["tasks"] if n["action"] == spec["action"] and n["target"] == spec["target"]), None)
    if node is None:
        return _result("outside_task_plan", "The operation is outside the current requested plan.")
    if prior_writes is not None:
        # During journal replay, earlier writes have already been validated.
        # The read/consent prefix deliberately strips write metadata to avoid
        # recursively replaying the entire write journal for every send.
        if node["conflicts"]:
            return _result(node["conflicts"][0]["code"], "Resolve conflicting requests first.")
        for dependency in node["depends_on"]:
            required = next(n for n in state["tasks"] if n["id"] == dependency)
            if not any(o["mutates"] and o["status"] == "succeeded" and not o["persistence_unresolved"] and o["sent_index"] > node["plan_index"]
                       and o["spec"]["action"] == required["action"] and o["spec"]["target"] == required["target"] for o in prior_writes):
                return _result("dependency_result_required", "A verified prerequisite result is required.")
        return None
    assessed = inspect_task_plan(state)
    if assessed["code"] != "task_plan_assessed":
        return assessed
    result = next(n["assessment"] for n in assessed["details"]["tasks"] if n["id"] == node["id"])
    return None if result["decision"] == "allow" else result


def _known_quote_rule(spec, facts):
    if spec["action"] not in {"modify_items", "exchange"}:
        return None
    items = facts["order"]["items"]
    catalog = {r["item"]["item_id"]: r["item"] for r in facts["catalog"]}
    pairs = [[next(i["price"] for i in items if i["item_id"] == p["existing_item_id"]),
              catalog[p["replacement_item_id"]]["price"]] for p in spec["parameters"]["replacements"]]
    try:
        difference = price_difference(pairs)
    except (TypeError, ValueError):
        return _result("price_difference_unavailable", "The complete price difference cannot be represented safely.")
    if difference != spec["amount"]["value"]:
        return _result("price_difference_mismatch", "The complete quote differs from the documented ordered float calculation; prepare a new proposal.")
    method = settlement_method_rule(spec["action"], facts["customer"]["payment_methods"],
                                    spec["parameters"]["payment_method_id"], spec["amount"]["value"])
    return None if method["decision"] == "allow" else method


def _read(state, api, name, selectors, tag):
    call_id = f"{tag}:{len(state['operations'])}"
    call = ToolAction(call_id, name, bind_arguments(name, selectors, state))
    record_decision(state, Decision(calls=(call,)))
    try:
        # This trusted internal path has full validated session provenance.
        # Re-searching mutable postal data after an address change cannot
        # establish (or revoke) the already-proved identity. Model-facing
        # standalone tools retain their original strict verification path.
        from support_agent.adapters.client_api import request_object
        if name == "read_customer_profile":
            body = request_object(api, "GET", "/v1/customers/" + read_api.identifier(call.arguments["customer_id"]))
        elif name == "get_order":
            body = read_api._owned_order(api, state["customer_record"], call.arguments["order_id"])
        elif name in {"get_product", "get_item"}:
            key = "product_id" if name == "get_product" else "item_id"
            collection = "products" if name == "get_product" else "items"
            body = request_object(api, "GET", f"/v1/catalog/{collection}/" + read_api.identifier(call.arguments[key]))
            body = read_api.validate_catalog(body, name, call.arguments)
        else:
            raise ValueError("Unsupported internal refresh selector")
        outcome = ToolOutcome(call_id, json.dumps(body, allow_nan=False))
    except (ClientAPIError, ValueError, TypeError, KeyError, OverflowError):
        outcome = ToolOutcome(call_id, "", True)
    status, _ = consume_results(state, (outcome,))
    state["history"].append(result_history((outcome,), status=status))
    return call_id, status


def _selectors(spec, facts, *, catalog=True):
    reads = [("read_customer_profile", {})]
    if "order_id" in spec["target"]:
        reads.append(("get_order", {"order_id": spec["target"]["order_id"]}))
    if catalog:
        seen = set()
        for row in facts["catalog"]:
            source = row["source"]
            key = (source["tool_name"], source.get("product_id", row["item"]["item_id"]))
            if key not in seen:
                reads.append((key[0], {"product_id" if key[0] == "get_product" else "item_id": key[1]}))
                seen.add(key)
    return reads


def refresh_proposal(state, version, specification, client_api):
    """Accepted READ path, not authorization; stale/failed refresh cannot pass."""
    state = clone_state(state)
    consent = check_confirmation(state, version, specification)
    if consent["decision"] != "allow":
        return _closed(consent), state
    spec = normalize_spec(specification)
    blocked = _write_block(state, version, spec) or _task_block(state, spec)
    if blocked:
        return blocked, state
    facts = _scope_facts(state["history"], spec)
    reads = _selectors(spec, facts)
    if state["tool_calls_since_user"] + len(reads) > 12:
        return _result("refresh_budget_exceeded", "The complete refresh exceeds this request's read budget."), state
    ids = []
    for name, selectors in reads:
        try:
            call_id, status = _read(state, client_api, name, selectors, "refresh")
        except ValueError:
            return _result("refresh_scope_changed", "Fresh customer references no longer authorize the selected read."), clone_state(state)
        ids.append(call_id)
        if status != "succeeded":
            return _result("refresh_failed", "A required refresh failed or was rejected; no old body replaces it.", read_ids=ids), clone_state(state)
    consent = check_confirmation(state, version, spec)
    if consent["decision"] != "allow":
        return _closed(consent), clone_state(state)
    facts = _scope_facts(state["history"], spec)
    if facts["order"] is not None:
        guard = fulfillment_rule(facts["order"], spec["action"])
        if guard["decision"] != "allow":
            return _closed(guard), clone_state(state)
    quote = _known_quote_rule(spec, facts)
    if quote:
        return _closed(quote), clone_state(state)
    return _result("write_preflight_checked", "Consent and required facts remain consistent; runtime and business gates are still mandatory.",
                   decision="allow", read_ids=ids), clone_state(state)


def _fresh_reads(history, spec, ids, after, *, catalog):
    """Bind exact accepted calls/results after confirmation or receipt, not time."""
    prefix = initial_state(_clean_read_history(history))
    facts = _scope_facts(history, spec, state_only=not catalog)
    expected = _selectors(spec, facts, catalog=catalog)
    if not isinstance(ids, list) or len(ids) != len(expected) or len(set(ids)) != len(ids):
        raise InvalidWrite("Complete ordered refresh IDs are required")
    succeeded = {o["call_id"] for o in prefix["operations"] if o["status"] == "succeeded"}
    positions = {}
    for i, entry in enumerate(history):
        for call in entry.get("tool_calls", []) if entry["role"] == "assistant" else []:
            positions[call["id"]] = (i, call)
    last = after
    for call_id, (name, selectors) in zip(ids, expected):
        index, call = positions.get(call_id, (-1, {}))
        if (call_id not in succeeded or index <= last or call.get("name") != name
                or any(call["arguments"].get(k) != v for k, v in selectors.items())):
            raise InvalidWrite("Refresh is missing, stale, failed or outside scope")
        relevant = [(i, c) for i, c in positions.values() if c.get("name") == name
                    and all(c["arguments"].get(k) == v for k, v in selectors.items())]
        if index != max(i for i, _ in relevant):
            raise InvalidWrite("A later attempt supersedes this refresh")
        last = index
    return facts


def restore_write_event(state, index):
    """Replay trusted journal metadata, never perform I/O or resend."""
    entry = state["history"][index]
    if set(entry) != {"role", "content", "write_event"} or entry["role"] != "assistant":
        raise InvalidWrite("Write events require an isolated assistant journal entry")
    event = entry["write_event"]
    if not isinstance(event, dict) or entry["content"] != "Operation journal: " + json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False):
        raise InvalidWrite("Journal text and metadata disagree")
    kind = event.get("kind")
    if kind == "sent":
        if set(event) != {"kind", "call_id", "version", "spec", "read_ids"}:
            raise InvalidWrite("Invalid sent event")
        spec = normalize_spec(event["spec"])
        prefix = initial_state([{k: v for k, v in e.items() if k != "write_event"} for e in state["history"][:index]])
        consent = check_confirmation(prefix, event["version"], spec)
        if consent["decision"] != "allow" or _write_block(state, event["version"], spec) or _task_block(prefix, spec, prior_writes=state["operations"]):
            raise InvalidWrite("Sent event lacks current consent or repeats a write")
        record = next(p for p in _current_records(prefix) if p["version"] == event["version"])
        after = max(record["confirmation"]["history_index"], record["presentation_index"])
        facts = _fresh_reads(state["history"][:index], spec, event["read_ids"], after, catalog=True)
        if facts["order"] is not None and fulfillment_rule(facts["order"], spec["action"])["decision"] != "allow":
            raise InvalidWrite("Unresolved fulfillment evidence")
        if _known_quote_rule(spec, facts):
            raise InvalidWrite("Quote or settlement method violates known rules")
        if event["call_id"] != f"write:{index}:{event['version']}":
            raise InvalidWrite("Write ID does not bind its journal position")
        state["operations"].append({"call_id": event["call_id"], "name": spec["action"], "mutates": True,
                                    "status": "sent", "version": event["version"], "spec": spec,
                                    "read_ids": event["read_ids"], "receipt": None, "verified_read_ids": [], "sent_index": index,
                                    "persistence_unresolved": False})
    elif kind == "checkpoint_uncertain":
        op = next((o for o in state["operations"] if o["mutates"] and o["call_id"] == event.get("call_id")), None)
        phases = {"sent": {"sent"}, "result": {"acknowledged", "failed", "unknown"}, "verified": {"succeeded"}}
        if (set(event) != {"kind", "call_id", "phase"} or op is None or event["phase"] not in phases
                or op["status"] not in phases[event["phase"]] or op["persistence_unresolved"]):
            raise InvalidWrite("Invalid checkpoint uncertainty event")
        op["persistence_unresolved"] = True
    elif kind in {"result", "verified"}:
        op = next((o for o in state["operations"] if o["mutates"] and o["call_id"] == event.get("call_id")), None)
        if op is None:
            raise InvalidWrite("Result lacks a recorded send")
        if kind == "result":
            if set(event) != {"kind", "call_id", "status", "receipt", "code"} or op["status"] != "sent":
                raise InvalidWrite("Duplicate or malformed write result")
            codes = {"acknowledged": "write_receipt_accepted", "failed": "write_rejected", "unknown": "write_result_unknown"}
            if event["status"] not in codes or event["code"] != codes[event["status"]]:
                raise InvalidWrite("Invalid write result classification")
            receipt = normalize_receipt(op["spec"], event["receipt"]) if event["status"] == "acknowledged" else None
            if receipt != event["receipt"]:
                raise InvalidWrite("Failed/unknown result cannot carry accepted facts")
            op.update(status=event["status"], receipt=receipt, result_index=index, result_code=event["code"])
        else:
            if set(event) != {"kind", "call_id", "read_ids"} or op["status"] != "acknowledged":
                raise InvalidWrite("Only an acknowledged write can be verified")
            facts = _fresh_reads(state["history"][:index], op["spec"], event["read_ids"], op["result_index"], catalog=False)
            before = _scope_facts(state["history"][:op["sent_index"]], op["spec"])
            if not receipt_matches_readback(op["spec"], op["receipt"], facts, before):
                raise InvalidWrite("Receipt and owned strong readback disagree")
            op.update(status="succeeded", verified_read_ids=event["read_ids"])
    else:
        raise InvalidWrite("Unsupported write journal event")


def validate_write_operations(state):
    replay = {"history": [], "operations": []}
    for i, entry in enumerate(state["history"]):
        replay["history"].append(entry)
        if "write_event" in entry:
            restore_write_event(replay, i)
    actual = [o for o in state["operations"] if o["mutates"]]
    if replay["operations"] != actual:
        raise InvalidWrite("Write operations differ from their original journal")


def _append_event(state, event):
    index = len(state["history"])
    state["history"].append({"role": "assistant", "content": "Operation journal: " + json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False), "write_event": event})
    restore_write_event(state, index)


def _checkpoint_uncertain(state, call_id, phase):
    # Keep observed receipt/effect evidence, but do not use an unacknowledged
    # persistence boundary to release dependencies or send another operation.
    _append_event(state, {"kind": "checkpoint_uncertain", "call_id": call_id, "phase": phase})
    return clone_state(state)


def _runtime_gate(result):
    try:
        result = json.loads(json.dumps(result, allow_nan=False))
    except (TypeError, ValueError):
        result = None
    if (not isinstance(result, dict) or result.get("decision") not in {"allow", "deny", "needs_information"}
            or not isinstance(result.get("code"), str) or not isinstance(result.get("message"), str)
            or not isinstance(result.get("rules"), list) or any(not isinstance(r, str) for r in result["rules"])
            or not isinstance(result.get("details"), dict)):
        return _result("invalid_runtime_assessment", "The trusted runtime assessment is malformed.", decision="deny", input_error=True)
    return None if result["decision"] == "allow" else {**result, "details": {**result["details"], "write_authorized": False}}


def _assess(runtime, method, *arguments):
    try:
        return _runtime_gate(getattr(runtime, method)(*arguments))
    except Exception:
        return _result("runtime_assessment_failed", "The trusted runtime assessment failed; no send or retry is permitted.")


def _verify_acknowledged(state, operation, runtime):
    ids = []
    spec, call_id = operation["spec"], operation["call_id"]
    facts = _scope_facts(state["history"], spec, state_only=True)
    for name, selectors in _selectors(spec, facts, catalog=False):
        if state["tool_calls_since_user"] >= 12:
            return _result("write_verification_unresolved", "Readback budget is exhausted; receipt alone does not prove completion."), clone_state(state)
        try:
            read_id, read_status = _read(state, runtime.client_api, name, selectors, "readback")
        except ValueError:
            return _result("write_verification_unresolved", "Readback scope is unresolved; do not resend."), clone_state(state)
        ids.append(read_id)
        if read_status != "succeeded":
            return _result("write_verification_unresolved", "Strong readback failed; do not resend."), clone_state(state)
    try:
        _append_event(state, {"kind": "verified", "call_id": call_id, "read_ids": ids})
    except (InvalidWrite, ValueError):
        state["history"].pop()
        return _result("write_verification_unresolved", "Receipt and owned readback disagree; investigate without resending."), clone_state(state)
    try:
        runtime.checkpoint(clone_state(state))
    except Exception:
        return _result("checkpoint_unresolved", "Verified-state persistence was not acknowledged; do not resend."), _checkpoint_uncertain(state, call_id, "verified")
    return _result("write_verified", "The submitted operation receipt matches the owned strong readback; this does not establish refund arrival.", decision="allow", call_id=call_id), clone_state(state)


def reconcile_operation(state, call_id, runtime=None):
    """Readonly delayed verification; never resend or infer a missing receipt.

    Sent/Unknown without an authoritative receipt remains unresolved even when
    backend values match. There is no receipt lookup/idempotency API contract.
    """
    state = clone_state(state)
    operation = next((o for o in state["operations"] if o["mutates"] and o["call_id"] == call_id), None)
    if operation is None:
        return _result("write_operation_required", "Select an original recorded write operation."), state
    if operation["persistence_unresolved"]:
        return _result("checkpoint_unresolved", "Durable journal submission needs authoritative review; no automatic persistence repair or send."), state
    if operation["status"] == "succeeded":
        return _result("write_already_verified", "This receipt and strong readback were already verified.", decision="allow"), state
    if operation["status"] != "acknowledged":
        codes = {"sent": "write_sent_unresolved", "unknown": "write_result_unknown", "failed": "write_rejected"}
        return _result(codes[operation["status"]], "This original outcome cannot be replaced with matching backend values; no resend is permitted.",
                       decision="deny" if operation["status"] == "failed" else "needs_information", status=operation["status"]), state
    if not isinstance(runtime, WriteRuntime):
        return _result("write_runtime_required", "Authenticated readonly reconciliation requires the trusted runtime."), state
    if state["pending_calls"] or state["handoff"]["status"] != "not_requested":
        return _result("reconciliation_blocked", "Pending reads or handoff block reconciliation."), state
    gate = _assess(runtime, "assess_submission", clone_state(state), operation["version"], json.loads(json.dumps(operation["spec"])))
    if gate:
        return gate, state
    return _verify_acknowledged(state, operation, runtime)


def execute_operation(state, version, specification, runtime=None):
    """Internal orchestration, disabled unless a trusted runtime is injected.

    Checkpoint BEFORE the sole send. A restored sent/Unknown/acknowledged write
    cannot enter this path again, even with a different version for the record.
    No default HTTP write implementation or business workflow is installed.
    """
    state = clone_state(state)
    consent = check_confirmation(state, version, specification)
    if consent["decision"] != "allow":
        return _closed(consent), state
    spec = normalize_spec(specification)
    blocked = _write_block(state, version, spec) or _task_block(state, spec)
    if blocked:
        return blocked, state
    if not isinstance(runtime, WriteRuntime):
        return _result("write_runtime_required", "The default Agent has no authenticated business write runtime."), state
    gate = _assess(runtime, "assess_submission", clone_state(state), version, json.loads(json.dumps(spec)))
    if gate:
        return gate, state
    checked, state = refresh_proposal(state, version, spec, runtime.client_api)
    if checked["decision"] != "allow":
        return checked, state
    gate = _assess(runtime, "assess_business", clone_state(state), json.loads(json.dumps(spec)))
    if gate:
        return gate, state
    call_id = f"write:{len(state['history'])}:{version}"
    _append_event(state, {"kind": "sent", "call_id": call_id, "version": version, "spec": spec, "read_ids": checked["details"]["read_ids"]})
    try:
        if runtime.claim_sent(clone_state(state), call_id) is not True:
            raise WriteClaimConflict("Claim was not explicitly accepted")
    except WriteClaimConflict:
        return _result("write_already_claimed", "The durable runtime rejected a repeated or stale send claim; no send was attempted."), clone_state(state)
    except Exception:
        # Persistence may itself have partially succeeded. Do not send, retry,
        # pretend rollback, or erase the attempted checkpoint from evidence.
        return _result("checkpoint_unresolved", "Sent-state persistence was not acknowledged; no send was attempted."), _checkpoint_uncertain(state, call_id, "sent")
    receipt, status, code = None, "unknown", "write_result_unknown"
    try:
        body = runtime.send(json.loads(json.dumps(spec)))
        receipt = normalize_receipt(spec, body)
        status, code = "acknowledged", "write_receipt_accepted"
    except ClientAPIError as exc:
        status = "unknown" if exc.outcome_unknown else "failed"
        code = "write_result_unknown" if exc.outcome_unknown else "write_rejected"
    except Exception:
        # Send exceptions and unusable success bodies are outcome uncertainty.
        # Never retain raw exception text or a rejected partial response body.
        pass
    _append_event(state, {"kind": "result", "call_id": call_id, "status": status, "receipt": receipt, "code": code})
    try:
        runtime.checkpoint(clone_state(state))
    except Exception:
        return _result("checkpoint_unresolved", "Receipt persistence is unresolved; the operation will not be resent."), _checkpoint_uncertain(state, call_id, "result")
    if status != "acknowledged":
        return _result(code, "The operation was rejected or its result is unknown; no automatic retry is permitted.", decision="deny" if status == "failed" else "needs_information"), clone_state(state)
    operation = next(o for o in state["operations"] if o["call_id"] == call_id)
    return _verify_acknowledged(state, operation, runtime)
