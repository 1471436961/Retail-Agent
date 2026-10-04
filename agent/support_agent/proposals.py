"""Versioned complete-operation consent. No API or business-write authority.

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
from support_agent.domain.policies import cancellation_refund_basis, return_destination_rule
from support_agent.domain.catalog import resolve_return_items, return_refund_basis
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
        _keys(params, {"item_ids", "refund_payment_method_id"})
        if (not isinstance(params["item_ids"], list) or not params["item_ids"]
                or any(not identifier(i) for i in params["item_ids"])
                or not identifier(params["refund_payment_method_id"])):
            raise InvalidProposal("Complete original units and one refund destination are required")
        _keys(amount, {"kind", "value", "estimate_method"})
        if amount["kind"] != "estimated_refund" or amount["estimate_method"] != "original_prices_decimal_sum_half_up_cents":
            raise InvalidProposal("A labelled original-price display estimate is required")
        _number(amount["value"], nonnegative=True)
    if action in {"payment_method", "modify_items", "exchange"} and not identifier(params["payment_method_id"]):
        raise InvalidProposal("One exact payment method ID is required")
    return spec


def _clean_read_history(history):
    return [{k: v for k, v in entry.items() if k not in {"proposal", "proposal_ack", "proposal_set", "proposal_set_ack", "task_plan", "write_event"}} for entry in history]


def _return_opening_boundary(history, target):
    """Freeze at the first relevant explicit return request/presentation.

    The internal structured entry may precede a natural-language workflow; in
    that case its first presentation is the opening boundary. A later accepted
    profile cannot backfill it. M5 owns richer request/withdrawal interpretation.
    """
    boundary = len(history)
    for index, entry in enumerate(history):
        events = [entry["proposal"]] if "proposal" in entry else entry.get("proposal_set", [])
        if any(event.get("spec", {}).get("action") == "return" and event["spec"]["target"] == target for event in events):
            boundary = index
            break
    for index, entry in enumerate(history[:boundary]):
        if entry["role"] == "user" and re.search(r"\breturn\b|退货", entry["content"], re.I):
            explicit_orders = re.findall(r"#[A-Za-z0-9_-]+", entry["content"])
            if not explicit_orders or target["order_id"] in explicit_orders:
                return index, boundary
    return boundary, boundary


def _scope_facts(history, spec, *, state_only=False):
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
    calls, order, catalog, product_members, profiles = {}, None, {}, {}, []
    opening_index, presentation_boundary = _return_opening_boundary(history, target)
    for index, entry in enumerate(prefix["history"]):
        if entry["role"] == "assistant":
            calls.update({c["id"]: c for c in entry.get("tool_calls", [])})
        results = entry.get("tool_messages", []) if entry["role"] == "tools" else [entry] if entry["role"] == "tool" else []
        for result in results:
            call = calls.get(result["id"], {})
            if result["error"] or call.get("name") not in {"lookup_customer", "verify_customer", "read_customer_profile", "get_order", "list_customer_orders", "get_product", "get_item"}:
                continue
            body = json.loads(result["content"])
            if set(body) == {"read_result_status"}:
                continue  # M2 removed the entire rejected batch's fact bodies.
            if call["name"] in {"lookup_customer", "verify_customer", "read_customer_profile"}:
                if body.get("customer_id") == target["customer_id"] and index < presentation_boundary:
                    profiles.append((index, body["payment_methods"]))
                continue
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
    if state_only:
        # Task planning needs exact accepted state before there is a quote.
        # This returns facts only; the task caller must apply order_state_rule.
        return {"customer": prefix["customer_record"], "order": order, "catalog": []}
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
    if spec["action"] == "return":
        before_opening = [p for p in profiles if p[0] < opening_index]
        # If identity was collected after the initial request, opening becomes
        # the first successfully verified profile, not any later profile refresh.
        opening = before_opening[-1] if before_opening else profiles[0] if profiles else (None, None)
        opening_methods = opening[1]
        estimate = return_refund_basis(order["items"], spec["parameters"]["item_ids"])
        destination = return_destination_rule(prefix["customer_record"]["payment_methods"], order["payments"],
                    spec["parameters"]["refund_payment_method_id"], opening_payment_methods=opening_methods)
        if (estimate["decision"] != "allow" or destination["decision"] != "allow"
                or estimate["details"]["aggregate_amount"] != spec["amount"]["value"]):
            raise InvalidProposal("Return units, original-price estimate or destination do not match accepted facts")
        # Bind historical eligibility as well as current methods and prices.
        return {"customer": prefix["customer_record"], "order": order, "catalog": [],
                "opening_payment_methods": opening_methods, "opening_profile_index": opening[0]}
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
              "modify_items": "Modify this order's item variants", "exchange": "Request an exchange", "cancel": "Cancel this entire order",
              "return": "Request a return of the complete selected list"}
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
    elif action == "return":
        lines.append("Original units (occurrences preserved): " + json.dumps(params["item_ids"]))
        lines.append("Refund destination: " + params["refund_payment_method_id"])
        lines.append(f'Estimated original-price refund: {amount["value"]:.2f} (decimal sum, half-up cents).')
        lines.append("This estimate is not a settlement guarantee; the API receives no amount and refund arrival is not verified.")
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
    if "set_index" in proposal or proposal["status"] != "confirmed" or proposal["confirmation"] is None:
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
    if ("set_index" in proposal or proposal["status"] != "confirmed" or proposal["confirmation"] is None
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
    if "set_index" in state["proposals"][-1]:
        return _observe_set_user(state, index)
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
    _supersede_current(state)
    state["proposals"].append({**_copy(event), "presentation_index": index, "status": "proposed", "confirmation": None})


def validate_ledger(state):
    replay = {"history": [], "proposals": []}
    for index, entry in enumerate(state["history"]):
        replay["history"].append(entry)
        if "proposal" in entry:
            if entry["role"] != "assistant":
                raise InvalidProposal("Only the recorded assistant presentation carries proposal metadata")
            restore_presentation(replay, index)
        elif "proposal_set" in entry:
            restore_proposal_set(replay, index)
        elif "proposal_set_ack" in entry:
            restore_set_ack(replay, index)
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
        if (state["proposals"] and "set_index" not in state["proposals"][-1]
                and state["proposals"][-1]["status"] == "confirmed" and state["proposals"][-1]["fingerprint"] == digest):
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
    current = _current_records(state)
    proposal = next((p for p in current if p["version"] == version), None)
    if proposal is None:
        return outcome(deny, "version_mismatch", "Consent belongs to a different proposal version.")
    if _semantic_json(proposal["spec"]) != _semantic_json(spec):
        return outcome(deny, "specification_mismatch", "The requested operation differs from the presented proposal.")
    if "set_index" in proposal:
        if proposal["status"] == "withdrawn":
            return outcome(deny, "proposal_withdrawn", "The user withdrew this complete operation.")
        reason = proposal["response"]["kind"] if proposal["response"] else None
        if reason in {"condition", "amend", "deferred", "unresolved"}:
            code, message = {
                "condition": ("condition_unresolved", "Resolve the user's condition and recap the selected complete operation."),
                "amend": ("proposal_amended", "The affected list, method or quote needs a new complete recap."),
                "deferred": ("scope_not_confirmed", "The user did not confirm this operation in the displayed set."),
                "unresolved": ("response_unresolved", "The reply does not unambiguously confirm this displayed operation.")}[reason]
            return outcome(need, code, message)
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


def _current_records(state):
    if not state["proposals"]:
        return []
    last = state["proposals"][-1]
    if "set_index" not in last:
        return [last]
    return [p for p in state["proposals"] if p.get("set_index") == last["set_index"]]


def _supersede_current(state):
    for record in _current_records(state):
        record["status"], record["confirmation"] = "superseded", None


def _normalize_set(specifications):
    if not isinstance(specifications, list) or not specifications:
        raise InvalidProposal("A nonempty list of complete operation specifications is required")
    specs = [normalize_spec(s) for s in specifications]
    scopes = [(s["action"], json.dumps(s["target"], sort_keys=True)) for s in specs]
    if len(set(scopes)) != len(scopes):
        raise InvalidProposal("Duplicate operation scopes require one complete proposal")
    # Do not offer cancellation and modifications of that same order as if
    # both were independently executable. Task conflict planning belongs to M3.4.
    for spec in specs:
        if spec["action"] == "cancel" and any(
                other["target"] == spec["target"] and other["action"] != "cancel" for other in specs):
            raise InvalidProposal("Resolve cancellation versus other same-order operations first")
    return specs


def render_proposal_set(specifications, retained=()):
    specs = _normalize_set(specifications)
    sections = []
    for number, spec in enumerate(specs, 1):
        sections.append(f"Operation {number}:\n" + "\n".join(render_proposal(spec).splitlines()[:-1]))
        if number in retained:
            sections.append("Existing confirmation for this unchanged complete operation is retained.")
        if spec["action"] == "modify_items":
            sections.append("This operation includes the entire modification list, with no other modifications.")
    if len(retained) == len(specs):
        sections.append("All these unchanged complete operations retain existing confirmation; no new confirmation is requested.")
    else:
        sections.append("Do you confirm the remaining complete operations, or only specific numbered operations? "
                        "A changed item list, payment method or condition requires a new complete recap.")
    return "\n\n".join(sections)


def restore_proposal_set(state, index):
    """Validate every scope against its preceding facts before accepting any."""
    entry = state["history"][index]
    _keys(entry, {"role", "content", "proposal_set"})
    if entry["role"] != "assistant":
        raise InvalidProposal("Only assistant presentations carry operation sets")
    events = entry["proposal_set"]
    if not isinstance(events, list) or not events:
        raise InvalidProposal("Missing complete operation set")
    specs = _normalize_set([e.get("spec") if isinstance(e, dict) else None for e in events])
    retained = [i for i, e in enumerate(events, 1) if isinstance(e, dict) and e.get("reuse_version") is not None]
    if entry["content"] != render_proposal_set(specs, retained):
        raise InvalidProposal("Operation set differs from the displayed complete recap")
    request_index = next((i for i in range(index - 1, -1, -1) if state["history"][i]["role"] == "user"), None)
    staged = []
    previous = {p["version"]: p for p in _current_records(state)}
    for offset, (event, spec) in enumerate(zip(events, specs), 1):
        _keys(event, {"version", "spec", "request_index", "facts", "fingerprint", "reuse_version"})
        if (type(event["version"]) is not int or event["version"] != len(state["proposals"]) + offset
                or type(event["request_index"]) is not int or event["request_index"] != request_index
                or spec != event["spec"]):
            raise InvalidProposal("Invalid set version, original request or normalized specification")
        facts = _scope_facts(state["history"][:index], spec)
        if (json.dumps(facts, sort_keys=True, allow_nan=False) != json.dumps(event["facts"], sort_keys=True, allow_nan=False)
                or fingerprint(spec, facts) != event["fingerprint"]):
            raise InvalidProposal("Operation set facts or fingerprint differ")
        record = {**_copy(event), "presentation_index": index, "set_index": index,
                  "status": "proposed", "confirmation": None, "response": None}
        reuse = event["reuse_version"]
        if reuse is not None:
            old = previous.get(reuse) if type(reuse) is int else None
            if (old is None or old["status"] != "confirmed" or old["confirmation"] is None
                    or old["fingerprint"] != record["fingerprint"]):
                raise InvalidProposal("Retained consent must match a currently confirmed complete operation")
            record["status"], record["confirmation"] = "confirmed", _copy(old["confirmation"])
            record["response"] = {"kind": "retained", "history_index": old["confirmation"]["history_index"]}
        staged.append(record)
    _supersede_current(state)
    state["proposals"].extend(staged)


def present_proposals(state, specifications):
    """M3.3 trusted presentation of independently selectable complete operations.

    This is not a task scheduler or a model tool. New versions supersede prior
    records, with consent retained only for an unchanged confirmed exact scope
    and facts. A producer must resolve new quotes before re-presenting them.
    The legacy single-proposal API retains its schema-2 replay semantics.
    """
    from support_agent.state import clone_state
    state = clone_state(state)
    try:
        specs = _normalize_set(specifications)
        if state["pending_calls"] or state["handoff"]["status"] != "not_requested":
            raise InvalidProposal("Cannot present during pending reads or handoff")
        facts = [_scope_facts(state["history"], spec) for spec in specs]
        current = _current_records(state)
        if (current and "set_index" in current[0] and len(current) == len(specs)
                and all(p["status"] == "confirmed" and p["fingerprint"] == fingerprint(s, f)
                        for p, s, f in zip(current, specs, facts))):
            decision, state = record_set_ack(state)
            return decision, clone_state(state)
        request_index = next(i for i in range(len(state["history"]) - 1, -1, -1) if state["history"][i]["role"] == "user")
        events = [{"version": len(state["proposals"]) + offset, "spec": spec,
                   "request_index": request_index, "facts": fact, "fingerprint": fingerprint(spec, fact),
                   "reuse_version": next((p["version"] for p in current if p["status"] == "confirmed"
                                          and p["fingerprint"] == fingerprint(spec, fact)), None)}
                  for offset, (spec, fact) in enumerate(zip(specs, facts), 1)]
        text = render_proposal_set(specs, [i for i, e in enumerate(events, 1) if e["reuse_version"] is not None])
        state["history"].append({"role": "assistant", "content": text, "proposal_set": events})
        restore_proposal_set(state, len(state["history"]) - 1)
        return Decision(text=text), clone_state(state)
    except (TypeError, ValueError, KeyError, StopIteration) as exc:
        raise InvalidProposal(str(exc)) from exc


def _scope_selection(text, records):
    """Resolve entire visible operation labels, never individual item IDs."""
    # Full matches prevent a suffix like 'if cheap' or 'except item X' from
    # being lost. Ambiguous action labels across orders are unresolved.
    if text in {"all", "all operations", "全部", "全部操作"}:
        return list(range(len(records)))
    numbered = re.fullmatch(r"operations? ([1-9]\d*(?:(?:, | and )[1-9]\d*)*)", text)
    chinese = re.fullmatch(r"第[1-9]\d*项(?:(?:、|和)第[1-9]\d*项)*", text)
    if numbered or chinese:
        indexes = [int(n) - 1 for n in re.findall(r"\d+", text)]
        return indexes if len(set(indexes)) == len(indexes) and all(i < len(records) for i in indexes) else None
    labels = {"the order address": "shipping_address", "order address": "shipping_address", "订单地址": "shipping_address",
              "the default address": "default_shipping_address", "default address": "default_shipping_address", "默认地址": "default_shipping_address",
              "the payment method": "payment_method", "payment method": "payment_method", "支付方式": "payment_method",
              "the item modifications": "modify_items", "item modifications": "modify_items", "商品修改": "modify_items",
              "the exchange": "exchange", "exchange": "exchange", "换货": "exchange",
              "the cancellation": "cancel", "cancellation": "cancel", "取消订单": "cancel"}
    matched = [i for i, p in enumerate(records) if p["spec"]["action"] == labels.get(text)]
    return matched if len(matched) == 1 else None


def _classify_set_reply(text, records):
    """Bounded offline grammar. Unresolved prose cannot grant any consent."""
    text = re.sub(r"\s+", " ", text.strip()).casefold().rstrip(".!。！")
    all_scopes = list(range(len(records)))
    if _whole_assent(text) or text in {"confirm all", "确认全部", "全部确认"}:
        return "confirm", [("confirm", all_scopes)]
    if text in {"no", "do not proceed", "don't proceed", "withdraw all", "cancel these changes",
                "不", "不同意", "不要执行", "全部撤回", "撤回全部", "什么都不改", "什么都不换"}:
        return "withdraw", [("withdraw", all_scopes)]
    # Explicit independent clauses are allowed; every clause must resolve and
    # their scopes must be disjoint. Never extract a 'yes' out of mixed prose.
    clauses = re.split(r"\s*;\s*|；", text)
    assignments, seen = [], set()
    for clause in clauses:
        condition = re.fullmatch(r"(?:confirm|change) (operation [1-9]\d*) (?:if|unless|when|after|before) .+|(?:确认|修改)(第[1-9]\d*项)(?:如果|只要|前提是).+", clause)
        confirm = re.fullmatch(r"(?:i )?confirm (?:only )?(.+)|(?:只|仅)?确认(.+)", clause)
        withdraw = re.fullmatch(r"withdraw (.+)|撤回(.+)", clause)
        amend = re.fullmatch(r"change (operation [1-9]\d*) .+|修改(第[1-9]\d*项).+", clause)
        match = condition or confirm or withdraw or amend
        if match is None:
            break
        selection = _scope_selection(next(v for v in match.groups() if v is not None), records)
        if selection is None or seen.intersection(selection):
            break
        kind = "condition" if condition else "confirm" if confirm else "withdraw" if withdraw else "amend"
        assignments.append((kind, selection))
        seen.update(selection)
    else:
        return "partial" if seen != set(all_scopes) or len(assignments) > 1 else assignments[0][0], assignments
    if re.search(r"\b(if|unless|provided|when|after|before)\b|如果|只要|除非|前提|之后|以后|先.*再", text):
        return "condition", [("condition", all_scopes)]
    if re.search(r"\b(add|change|instead|but|only|withdraw|cancel|confirm)\b|追加|再加|改为|改成|不过|但是|只|撤回|取消|确认", text):
        return "amend", [("amend", all_scopes)]
    return "unresolved", [("unresolved", all_scopes)]


def _observe_set_user(state, index):
    entry = state["history"][index]
    if entry["role"] != "user":
        raise InvalidProposal("Operation consent requires original user text")
    records = _current_records(state)
    kind, assignments = _classify_set_reply(entry["content"], records)
    previous = state["history"][index - 1] if index else {}
    if kind == "confirm" and "proposal_set_ack" in previous:
        restore_set_ack(state, index - 1)
        return {"kind": "set_ack"}  # Only the originally confirmed subset.
    fresh = index == records[0]["presentation_index"] + 1
    if any(action == "confirm" for action, _ in assignments) and not fresh:
        kind, assignments = "unresolved", [("unresolved", list(range(len(records))))]
    affected = set()
    for action, selection in assignments:
        for i in selection:
            p = records[i]
            affected.add(i)
            if action == "confirm" and p["status"] == "confirmed":
                continue  # Preserve the original exact-scope user evidence.
            p["response"] = {"kind": action, "history_index": index}
            p["status"] = "confirmed" if action == "confirm" else "withdrawn" if action == "withdraw" else "needs_review"
            p["confirmation"] = {"history_index": index, "fingerprint": p["fingerprint"]} if action == "confirm" else None
    if fresh:
        excludes_others = re.search(r"\bonly\b|只确认|仅确认", entry["content"].casefold()) is not None
        for i, p in enumerate(records):
            if i not in affected:
                if p["status"] == "confirmed" and not excludes_others:
                    continue
                p["status"], p["confirmation"] = "needs_review", None
                p["response"] = {"kind": "deferred", "history_index": index}
    if any(action == "confirm" for action, _ in assignments):
        return {"kind": "set_ack"}
    if kind == "partial":
        kind = "condition" if any(action == "condition" for action, _ in assignments) else "amend" if any(action == "amend" for action, _ in assignments) else "withdraw"
    messages = {"withdraw": "The specified proposals are withdrawn. No business write has been executed.",
                "amend": "The affected proposal needs a new complete list, quote and recap before confirmation.",
                "condition": "The condition is unresolved. It must be checked and the chosen complete operation recapped before confirmation."}
    return {"kind": "review", "text": messages[kind]} if kind in messages else None


def _set_ack_event(state):
    return [{"version": p["version"], "fingerprint": p["fingerprint"], "confirmation_index": p["confirmation"]["history_index"]}
            for p in _current_records(state) if p["status"] == "confirmed" and p["confirmation"] is not None]


def record_set_ack(state):
    records, events = _current_records(state), _set_ack_event(state)
    if not records or "set_index" not in records[0] or not events:
        raise InvalidProposal("Scoped acknowledgement requires existing user consent")
    numbers = [str(i) for i, p in enumerate(records, 1) if p["status"] == "confirmed"]
    text = "Confirmation recorded only for operation(s) " + ", ".join(numbers) + ". Other operations are not confirmed. No business write has been executed."
    state["history"].append({"role": "assistant", "content": text, "proposal_set_ack": events})
    restore_set_ack(state, len(state["history"]) - 1)
    return Decision(text=text), state


def restore_set_ack(state, index):
    entry = state["history"][index]
    _keys(entry, {"role", "content", "proposal_set_ack"})
    events = entry["proposal_set_ack"]
    records = _current_records(state)
    if (entry["role"] != "assistant" or not isinstance(entry["content"], str) or not entry["content"]
            or not records or "set_index" not in records[0] or not isinstance(events, list) or not events):
        raise InvalidProposal("Invalid scoped acknowledgement")
    for event in events:
        _keys(event, {"version", "fingerprint", "confirmation_index"})
        if type(event["version"]) is not int or type(event["confirmation_index"]) is not int or not 0 <= event["confirmation_index"] < index:
            raise InvalidProposal("Invalid scoped acknowledgement reference")
    if events != _set_ack_event(state):
        raise InvalidProposal("Scoped acknowledgement differs from original user consent")
