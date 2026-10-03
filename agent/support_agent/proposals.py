"""Versioned whole-proposal consent. No API calls or business-write authority.

Only trusted workflow code may present a structured proposal. Model candidates
have no proposal/confirmed surface. Raw user messages provide consent evidence;
the digest detects semantic mismatches, not malicious replacement of all state.
"""
from __future__ import annotations

import hashlib
import json
import re

from support_agent.domain.money import finite_amount, finite_number
from support_agent.domain.orders import ORDER_ACTIONS, order_state_rule
from support_agent.domain.policies import cancellation_refund_basis
from support_agent.domain.catalog import resolve_return_items
from support_agent.domain.rules import identifier, allow, deny, need
from support_agent.protocol import Decision


class InvalidProposal(ValueError):
    """Incomplete proposal, unsupported evidence or inconsistent consent."""


def _copy(value):
    # Do not let JSON silently convert tuples or non-string keys into evidence.
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise InvalidProposal("Proposal keys must be strings")
            for v in item.values():
                check(v)
        elif isinstance(item, list):
            for v in item:
                check(v)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise InvalidProposal("Proposal values must be JSON values")
    check(value)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvalidProposal("Proposal must contain finite JSON values") from exc


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise InvalidProposal("Incomplete or unsupported proposal fields")


def _number(value, *, nonnegative=False):
    try:
        return finite_amount(value) if nonnegative else finite_number(value)
    except (TypeError, ValueError) as exc:
        raise InvalidProposal("A finite resolved monetary amount is required") from exc


def normalize_spec(spec):
    spec = _copy(spec)
    _keys(spec, {"action", "target", "parameters", "amount"})
    action = spec["action"]
    if not isinstance(action, str) or action not in ORDER_ACTIONS | {"default_shipping_address"}:
        raise InvalidProposal("Unsupported proposal action")
    target = spec["target"]
    _keys(target, {"customer_id"} if action == "default_shipping_address" else {"customer_id", "order_id"})
    if any(not identifier(v) for v in target.values()):
        raise InvalidProposal("Exact record identifiers are required")
    params, amount = spec["parameters"], spec["amount"]
    if action in {"default_shipping_address", "shipping_address"}:
        _keys(params, {"address_line_1", "city", "region", "country", "postal_code"}, {"address_line_2"})
        if any(not identifier(params[k]) for k in ("address_line_1", "city", "region", "country", "postal_code")):
            raise InvalidProposal("A complete address is required")
        params.setdefault("address_line_2", None)
        if params["address_line_2"] is not None and not isinstance(params["address_line_2"], str):
            raise InvalidProposal("Invalid address line 2")
        _keys(amount, {"kind"})
        if amount["kind"] != "not_applicable":
            raise InvalidProposal("Address proposals have no monetary quote")
    elif action in {"modify_items", "exchange"}:
        _keys(params, {"replacements", "payment_method_id"})
        pairs = params["replacements"]
        if not isinstance(pairs, list) or not pairs:
            raise InvalidProposal("The complete nonempty replacement list is required")
        for pair in pairs:
            _keys(pair, {"existing_item_id", "replacement_item_id"})
            if any(not identifier(v) for v in pair.values()):
                raise InvalidProposal("Replacement IDs must be strings")
        _keys(amount, {"kind", "value"})
        if amount["kind"] != "price_difference":
            raise InvalidProposal("A complete price difference is required")
        _number(amount["value"])
    elif action == "payment_method":
        _keys(params, {"payment_method_id"})
        _keys(amount, {"kind", "value", "refund_rows"})
        if amount["kind"] != "order_total":
            raise InvalidProposal("A resolved full order amount is required")
        _number(amount["value"], nonnegative=True)
        basis = cancellation_refund_basis(amount["refund_rows"])
        if basis["decision"] != "allow" or basis["details"]["charges"] != amount["refund_rows"]:
            raise InvalidProposal("Original payment refund destinations are required")
    elif action == "cancel":
        _keys(params, {"reason"})
        if params["reason"] not in ("no longer needed", "ordered by mistake"):
            raise InvalidProposal("A resolved cancellation reason is required")
        _keys(amount, {"kind", "rows"})
        if amount["kind"] != "per_charge_refunds":
            raise InvalidProposal("Original charge rows are required")
        basis = cancellation_refund_basis(amount["rows"])
        if basis["decision"] != "allow" or basis["details"]["charges"] != amount["rows"]:
            raise InvalidProposal("Only original charge rows may form the refund basis")
    else:
        # M3.1 still has no applicable return aggregation evidence. A caller's
        # numeric estimate or confirmed flag cannot fill that evidence gap.
        raise InvalidProposal("Return refund aggregation evidence is still unavailable")
    if action in {"payment_method", "modify_items", "exchange"} and not identifier(params["payment_method_id"]):
        raise InvalidProposal("One exact payment method ID is required")
    return spec


def _clean_read_history(history):
    return [{k: v for k, v in entry.items() if k not in {"proposal", "proposal_ack"}} for entry in history]


def _scope_facts(history, spec):
    """Replay M2's accepted prefix, never HTTP, to establish original scope."""
    from support_agent.state import initial_state
    from support_agent.adapters.read_api import customer_order_ids
    prefix = initial_state(_clean_read_history(history))
    target = spec["target"]
    if (not prefix["identity"]["verified"] or not prefix["identity_evidence"]
            or prefix["identity"]["customer_id"] != target["customer_id"] or prefix["pending_calls"]
            or prefix["handoff"]["status"] != "not_requested"):
        raise InvalidProposal("Proposal requires verified, idle session evidence")
    if spec["action"] == "default_shipping_address":
        return {"customer": prefix["customer_record"], "order": None, "catalog": []}
    if target["order_id"] not in customer_order_ids(prefix["customer_record"]):
        raise InvalidProposal("Proposal target is outside the customer's references")
    calls, order, catalog, product_members = {}, None, {}, {}
    for entry in prefix["history"]:
        if entry["role"] == "assistant":
            calls.update({c["id"]: c for c in entry.get("tool_calls", [])})
        results = entry.get("tool_messages", []) if entry["role"] == "tools" else [entry] if entry["role"] == "tool" else []
        for result in results:
            call = calls.get(result["id"], {})
            if result["error"] or call.get("name") not in {"get_order", "list_customer_orders", "get_product", "get_item"}:
                continue
            body = json.loads(result["content"])
            if set(body) == {"read_result_status"}:
                continue  # M2 removed the entire rejected batch's fact bodies.
            # M2 has validated the whole batch. Sources remain verifiable on
            # replay, while repeated same-value reads do not change consent.
            if call["name"] in {"get_product", "get_item"}:
                source = {"call_id": result["id"], "tool_name": call["name"]}
                if call["name"] == "get_product":
                    product_id = body["product_id"]
                    source["product_id"] = product_id
                    records = body["items"]
                    members = {item["item_id"] for item in records}
                    for missing in product_members.get(product_id, set()) - members:
                        catalog.pop(missing, None)
                    product_members[product_id] = members
                else:
                    records = [body]
                for item in records:
                    catalog[item["item_id"]] = {"item": {k: item[k] for k in ("item_id", "price", "available", "options")},
                                               "source": dict(source)}
                continue
            records = body.get("orders", []) if call["name"] == "list_customer_orders" else [body]
            for record in records:
                if record.get("order_id") == target["order_id"] and record.get("customer_id") == target["customer_id"]:
                    order = record
    if order is None:
        raise InvalidProposal("An accepted owned order read is required")
    if order_state_rule(order, spec["action"])["decision"] != "allow":
        raise InvalidProposal("Order state does not permit this proposal")
    dependencies = []
    if spec["action"] in {"modify_items", "exchange"}:
        selected = resolve_return_items(order["items"], [p["existing_item_id"] for p in spec["parameters"]["replacements"]])
        if selected["decision"] != "allow":
            raise InvalidProposal("Selected original units are not fully resolved")
        for pair in spec["parameters"]["replacements"]:
            resolved = catalog.get(pair["replacement_item_id"])
            if resolved is None or resolved["item"]["available"] is not True:
                raise InvalidProposal("An accepted available target catalog record is required")
            dependencies.append(resolved)
    if spec["action"] in {"payment_method", "modify_items", "exchange"}:
        methods = prefix["customer_record"].get("payment_methods")
        if not isinstance(methods, list) or any(not isinstance(m, dict) or not identifier(m.get("id")) for m in methods):
            raise InvalidProposal("Complete saved method records are required")
        if spec["parameters"]["payment_method_id"] not in {m["id"] for m in methods}:
            raise InvalidProposal("Chosen payment method must be saved in the accepted profile")
    if spec["action"] in {"cancel", "payment_method"}:
        basis = cancellation_refund_basis(order["payments"])
        rows = spec["amount"]["rows" if spec["action"] == "cancel" else "refund_rows"]
        if basis["decision"] != "allow" or basis["details"]["charges"] != rows:
            raise InvalidProposal("Refund rows must match the accepted original charges")
    return {"customer": prefix["customer_record"], "order": order, "catalog": dependencies}


def _semantic_json(value):
    """Typed semantic encoding: equal finite numbers match, bool stays distinct.

    Exact integer ratios avoid float coercion of large integers. This changes
    comparison only, never stored amounts or any monetary calculation.
    """
    if type(value) in (int, float):
        numerator, denominator = (value, 1) if type(value) is int else value.as_integer_ratio()
        return ["number", str(numerator), str(denominator)]
    if isinstance(value, dict):
        return ["object", [[key, _semantic_json(value[key])] for key in sorted(value)]]
    if isinstance(value, list):
        return ["array", [_semantic_json(item) for item in value]]
    return ["boolean" if type(value) is bool else "null" if value is None else "string", value]


def fingerprint(spec, facts):
    # Provenance is checked exactly in restore_presentation; source call IDs
    # are not semantic changes when a later accepted read returns equal facts.
    semantic_facts = {**facts, "catalog": [row["item"] for row in facts.get("catalog", [])]}
    body = json.dumps(_semantic_json({"spec": spec, "facts": semantic_facts}), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def render_proposal(spec):
    """Deterministic complete recap; no customer-facing hash/state fields."""
    action, target, params, amount = (spec[k] for k in ("action", "target", "parameters", "amount"))
    labels = {"default_shipping_address": "Update the customer's default shipping address",
              "shipping_address": "Update this order's shipping address", "payment_method": "Switch this order's payment method",
              "modify_items": "Modify this order's item variants", "exchange": "Request an exchange", "cancel": "Cancel this entire order"}
    lines = [labels[action] + ".", "Customer: " + target["customer_id"]]
    if "order_id" in target:
        lines.append("Order: " + target["order_id"])
    if action in {"default_shipping_address", "shipping_address"}:
        for key in ("address_line_1", "address_line_2", "city", "region", "country", "postal_code"):
            lines.append(key.replace("_", " ").capitalize() + ": " + json.dumps(params[key], ensure_ascii=False))
    elif action == "cancel":
        lines.append("Reason: " + params["reason"])
        for row in amount["rows"]:
            lines.append("Original charge refund basis: " + str(row["amount"]) + " to " + row["payment_method_id"])
        lines.append("No aggregate refund amount or arrival is verified.")
    else:
        for pair in params.get("replacements", []):
            lines.append("Replace " + pair["existing_item_id"] + " with " + pair["replacement_item_id"])
        lines.append("Payment method: " + params["payment_method_id"])
        lines.append(("Full order charge: " if action == "payment_method" else "Signed price difference: ") + str(amount["value"]))
        for row in amount.get("refund_rows", []):
            lines.append("Original payment refund basis: " + str(row["amount"]) + " to " + row["payment_method_id"])
    lines.append("This is a proposal only; no change, charge or refund has been made.")
    if action == "modify_items":
        lines.append("Do you confirm this entire list is complete, with no other modifications, and want these exact changes?")
    else:
        lines.append("Do you want this exact complete operation?")
    return "\n".join(lines)


ACK = "Your confirmation of the complete proposal is recorded. No business write has been executed."


def record_ack(state, text=ACK):
    proposal = state["proposals"][-1]
    if proposal["status"] != "confirmed" or proposal["confirmation"] is None:
        raise InvalidProposal("Acknowledgement requires existing user consent")
    state["history"].append({"role": "assistant", "content": text, "proposal_ack": {
        "version": proposal["version"], "fingerprint": proposal["fingerprint"],
        "confirmation_index": proposal["confirmation"]["history_index"]}})
    restore_ack(state, len(state["history"]) - 1)
    return Decision(text=text), state


def restore_ack(state, index):
    entry = state["history"][index]
    _keys(entry, {"role", "content", "proposal_ack"})
    if entry["role"] != "assistant" or not isinstance(entry["content"], str) or not entry["content"] or not state["proposals"]:
        raise InvalidProposal("Invalid acknowledgement context")
    event, proposal = entry["proposal_ack"], state["proposals"][-1]
    _keys(event, {"version", "fingerprint", "confirmation_index"})
    if (proposal["status"] != "confirmed" or proposal["confirmation"] is None
            or type(event["version"]) is not int or event["version"] != proposal["version"]
            or type(event["confirmation_index"]) is not int
            or event["confirmation_index"] != proposal["confirmation"]["history_index"]
            or event["confirmation_index"] >= index or event["fingerprint"] != proposal["fingerprint"]):
        raise InvalidProposal("Acknowledgement differs from existing consent evidence")


def _whole_assent(text):
    # A conservative offline recognizer, not the business's approved vocabulary.
    # No substring search, model-provided flag, conditional or partial acceptance.
    normalized = re.sub(r"\s+", " ", text.strip()).casefold().rstrip(".!。！")
    return normalized in {"yes", "yes, please", "please proceed", "go ahead", "that's right", "i confirm", "i agree",
                          "是", "是的", "同意", "确认", "可以", "请继续", "确认以上全部变更", "就这些，确认修改"}


def observe_user(state, index):
    """Observe a recorded actual user message; never execute a business action."""
    if not state["proposals"]:
        return None
    proposal = state["proposals"][-1]
    entry = state["history"][index]
    if entry["role"] != "user":
        raise InvalidProposal("Confirmation must be an actual user message")
    affirmative = _whole_assent(entry["content"])
    if (proposal["status"] == "proposed" and affirmative and index == proposal["presentation_index"] + 1):
        proposal["status"] = "confirmed"
        proposal["confirmation"] = {"history_index": index, "fingerprint": proposal["fingerprint"]}
        return {"kind": "ack", "text": ACK}
    if (proposal["status"] == "confirmed" and affirmative and index > 0
            and "proposal_ack" in state["history"][index - 1]):
        restore_ack(state, index - 1)
        return {"kind": "ack", "text": ACK}  # Preserve the original evidence.
    if proposal["status"] in {"proposed", "confirmed"}:
        proposal["status"] = "needs_review"
        proposal["confirmation"] = None
    return {"kind": "review", "text": "That reply does not confirm a current complete proposal. Review and recap are required."} if affirmative else None


def restore_presentation(state, index):
    entry = state["history"][index]
    _keys(entry, {"role", "content", "proposal"})
    event = entry["proposal"]
    _keys(event, {"version", "spec", "request_index", "facts", "fingerprint"})
    if type(event["version"]) is not int or event["version"] != len(state["proposals"]) + 1:
        raise InvalidProposal("Proposal versions must increase without reuse")
    request_index = event["request_index"]
    if (type(request_index) is not int or not 0 <= request_index < index
            or state["history"][request_index]["role"] != "user"
            or any(e["role"] == "user" for e in state["history"][request_index + 1:index])):
        raise InvalidProposal("Proposal must bind the preceding actual user request")
    spec = normalize_spec(event["spec"])
    if spec != event["spec"] or entry["content"] != render_proposal(spec):
        raise InvalidProposal("Proposal recap and normalized semantic snapshot differ")
    facts = _scope_facts(state["history"][:index], spec)
    digest = fingerprint(spec, facts)
    if (json.dumps(event["facts"], sort_keys=True, allow_nan=False) != json.dumps(facts, sort_keys=True, allow_nan=False)
            or event["fingerprint"] != digest):
        raise InvalidProposal("Proposal facts or semantic fingerprint differ")
    if state["proposals"]:
        state["proposals"][-1]["status"] = "superseded"
        state["proposals"][-1]["confirmation"] = None
    state["proposals"].append({**_copy(event), "presentation_index": index, "status": "proposed", "confirmation": None})


def validate_ledger(state):
    replay = {"history": [], "proposals": []}
    for index, entry in enumerate(state["history"]):
        replay["history"].append(entry)
        if "proposal" in entry:
            if entry["role"] != "assistant":
                raise InvalidProposal("Only the recorded assistant presentation carries proposal metadata")
            restore_presentation(replay, index)
        elif "proposal_ack" in entry:
            restore_ack(replay, index)
        elif entry["role"] == "user":
            observe_user(replay, index)
    actual = json.dumps(state["proposals"], sort_keys=True, allow_nan=False, separators=(",", ":"))
    expected = json.dumps(replay["proposals"], sort_keys=True, allow_nan=False, separators=(",", ":"))
    if actual != expected:
        raise InvalidProposal("Proposal ledger does not match original message evidence")


def present_proposal(state, spec):
    """Trusted workflow entry point, deliberately absent from model/tool schema."""
    from support_agent.state import clone_state
    state = clone_state(state)
    try:
        spec = normalize_spec(spec)
        if state["pending_calls"] or state["handoff"]["status"] != "not_requested":
            raise InvalidProposal("Cannot present during pending calls or handoff")
        facts = _scope_facts(state["history"], spec)
        request_index = next(i for i in range(len(state["history"]) - 1, -1, -1) if state["history"][i]["role"] == "user")
        digest = fingerprint(spec, facts)
        if state["proposals"] and state["proposals"][-1]["status"] == "confirmed" and state["proposals"][-1]["fingerprint"] == digest:
            decision, state = record_ack(state)
            return decision, clone_state(state)
        event = {"version": len(state["proposals"]) + 1, "spec": spec, "request_index": request_index, "facts": facts, "fingerprint": digest}
        text = render_proposal(spec)
        state["history"].append({"role": "assistant", "content": text, "proposal": event})
        restore_presentation(state, len(state["history"]) - 1)
        return Decision(text=text), clone_state(state)
    except (TypeError, ValueError, KeyError, StopIteration) as exc:
        raise InvalidProposal(str(exc)) from exc


def check_confirmation(state, version, spec):
    """Explain consent matching only, never full business/write permission."""
    from support_agent.state import clone_state
    def outcome(builder, code, message):
        details = {"confirmation_matches": builder is allow}
        if code in {"invalid_version", "invalid_specification"}:
            details["input_error"] = True
        if code == "invalid_state":
            details["state_error"] = True
        return builder(code, message, "CF-01", "CF-02", details=details)
    if type(version) is not int or version < 1:
        return outcome(deny, "invalid_version", "A positive integer proposal version is required.")
    try:
        state = clone_state(state)
    except (TypeError, ValueError, KeyError):
        return outcome(deny, "invalid_state", "Session evidence is invalid; consent cannot be used.")
    try:
        spec = normalize_spec(spec)
    except (TypeError, ValueError, KeyError):
        return outcome(deny, "invalid_specification", "The proposal specification is incomplete or invalid.")
    if not state["proposals"]:
        return outcome(need, "proposal_required", "A complete proposal must be presented first.")
    proposal = state["proposals"][-1]
    if proposal["version"] != version:
        return outcome(deny, "version_mismatch", "Consent belongs to a different proposal version.")
    if _semantic_json(proposal["spec"]) != _semantic_json(spec):
        return outcome(deny, "specification_mismatch", "The requested operation differs from the presented proposal.")
    if proposal["status"] != "confirmed" or proposal["confirmation"] is None:
        return outcome(need, "confirmation_required", "The current complete proposal lacks valid user confirmation.")
    if state["handoff"]["status"] != "not_requested":
        return outcome(deny, "handoff_blocks_consent", "The session is blocked by a handoff.")
    if state["pending_calls"]:
        return outcome(need, "pending_reads", "Read results must be resolved before checking consent.")
    try:
        facts = _scope_facts(state["history"], spec)
    except (TypeError, ValueError, KeyError):
        return outcome(need, "facts_unavailable", "Required accepted facts or eligibility are unavailable.")
    if state["identity"]["customer_id"] != spec["target"]["customer_id"]:
        return outcome(deny, "identity_mismatch", "The proposal does not match the verified customer.")
    if proposal["fingerprint"] != fingerprint(spec, facts):
        return outcome(need, "facts_changed", "Accepted proposal dependencies changed; a new recap is required.")
    return outcome(allow, "consent_matches", "Original user consent matches this complete proposal only.")


def confirmation_matches(state, version, spec):
    """Boolean compatibility wrapper; malformed evidence always returns False."""
    return check_confirmation(state, version, spec)["details"]["confirmation_matches"]
