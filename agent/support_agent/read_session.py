"""State-bound read planning, result consumption and bounded model delegation."""
from __future__ import annotations

import json
import re

from support_agent.workflow_registry import WORKFLOW_KINDS
from support_agent.adapters.read_api import ORDER_STATUSES, customer_order_ids, validate_catalog, validate_order
from support_agent.domain.customer import customer_reply, find_customer_id
from support_agent.domain.identity import PROOF_FIELDS, fields_from_text, matches_customer, matches_session_customer, normalized, proof_from_text, supplied_by_user, verification_inputs
from support_agent.protocol import Decision, InvalidAction, READ_TOOL_FIELDS, ToolAction, TurnInput, validate_tool_action

MAX_READ_CALLS_PER_REQUEST = 12
# Enforce the current single-attempt flow. Multi-step business generation is a
# separate future workflow, with its own reachable budget tests.
MAX_MODEL_CALLS_PER_REQUEST = 1


def reply(state, text):
    state["history"].append({"role": "assistant", "content": text})
    return Decision(text=text), state


def bind_arguments(name: str, arguments: dict, state: dict) -> dict:
    """Fill only trusted session fields; conflicting model scope is rejected."""
    if state["handoff"]["status"] not in {"not_requested", "rejected"}:
        raise InvalidAction("Human transfer blocks business reads")
    if name not in READ_TOOL_FIELDS or not isinstance(arguments, dict) or set(arguments) - READ_TOOL_FIELDS[name]:
        raise InvalidAction("Unsupported read action or fields")
    if any(not isinstance(v, str) for v in arguments.values()):
        raise InvalidAction("Read arguments must be strings")
    args = dict(arguments)
    identity = state["identity"]
    if name in {"lookup_customer", "verify_customer"}:
        for key in READ_TOOL_FIELDS[name]:
            args.setdefault(key, "")
        proof = {k: args.get(k, "") for k in PROOF_FIELDS}
        if not supplied_by_user(proof, state["history"]):
            raise InvalidAction("Verification inputs must come from user messages")
        if identity["verified"]:
            if args["customer_id"] not in ("", identity["customer_id"]):
                raise InvalidAction("Cannot switch customers within this session")
            previous = state.get("identity_evidence")
            if previous and any(normalized(proof[k]) != normalized(previous["inputs"][k]) for k in PROOF_FIELDS):
                raise InvalidAction("Cannot replace session verification inputs")
            args["customer_id"] = identity["customer_id"]
    else:
        evidence = state.get("identity_evidence")
        if not identity["verified"] or not evidence or not supplied_by_user(evidence["inputs"], state["history"]):
            raise InvalidAction("Read requires verified session evidence")
        trusted = {"customer_id": identity["customer_id"], **evidence["inputs"]}
        for key, value in trusted.items():
            if key in args and normalized(args[key]) != normalized(value):
                raise InvalidAction("Read scope must match the verified session")
            args[key] = value
        if name == "list_customer_orders":
            args.setdefault("status", "")
            if args["status"] and args["status"] not in ORDER_STATUSES:
                raise InvalidAction("Unknown order status")
        if name == "get_order" and args.get("order_id") not in customer_order_ids(state["customer_record"]):
            raise InvalidAction("Order is not in the verified customer's references")
    validate_tool_action(ToolAction(id="gate", name=name, arguments=args))
    return args


def record_calls(state: dict, calls: tuple[ToolAction, ...]) -> None:
    Decision(calls=calls)
    if state["pending_calls"]:
        raise InvalidAction("Previous read batch is still pending")
    if state["tool_calls_since_user"] + len(calls) > MAX_READ_CALLS_PER_REQUEST:
        raise InvalidAction("Read budget exhausted")
    known = {o["call_id"] for o in state["operations"]}
    checked = []
    for call in calls:
        if call.id in known:
            raise InvalidAction("Reused tool call ID")
        args = bind_arguments(call.name, call.arguments, state)
        checked.append(ToolAction(id=call.id, name=call.name, arguments=args))
        known.add(call.id)
    if len(checked) > 1 and any(c.name in {"lookup_customer", "verify_customer"} for c in checked):
        raise InvalidAction("Verification must complete before other reads")
    for call in checked:
        state["pending_calls"][call.id] = {"name": call.name, "arguments": call.arguments, "mutates": False}
        state["operations"].append({"call_id": call.id, "name": call.name, "mutates": False, "status": "sent"})
    state["pending_call_id"] = checked[0].id if len(checked) == 1 else None
    state["tool_calls_since_user"] += len(checked)


def emit(state, name, arguments):
    call_id = f"lookup-{state['turn']}" if name == "lookup_customer" else f"read-{state['turn']}"
    decision = Decision(calls=(ToolAction(id=call_id, name=name, arguments=bind_arguments(name, arguments, state)),))
    record_decision(state, decision)
    return decision, state


def record_decision(state, decision):
    record_calls(state, decision.calls)
    calls = [{"id": c.id, "name": c.name, "arguments": dict(c.arguments)} for c in decision.calls]
    state["history"].append({"role": "assistant", "content": "", "tool_call_ids": [c.id for c in decision.calls], "tool_calls": calls})


def consume_results(state, outcomes):
    """Reject the entire malformed batch before accepting any identity or facts."""
    from support_agent.state import finish_pending
    pending = state["pending_calls"]
    if not pending:
        return "none", []
    ids = [r.id for r in outcomes]
    if len(ids) != len(set(ids)) or set(ids) != set(pending):
        finish_pending(state, "unknown")
        return "unknown", []
    staged = []
    try:
        for result in outcomes:
            descriptor = pending[result.id]
            if result.error:
                finish_pending(state, "failed")
                return "failed", []
            body = json.loads(result.content)
            if not isinstance(body, dict):
                raise ValueError("Read body is not an object")
            name, args = descriptor["name"], descriptor["arguments"]
            proof = {k: args.get(k, "") for k in PROOF_FIELDS}
            if name in {"lookup_customer", "verify_customer", "read_customer_profile"}:
                matches = (matches_session_customer(body, proof, args["customer_id"], state["history"])
                           if name == "read_customer_profile" and state["identity"]["verified"] and state["identity_evidence"]
                           else matches_customer(body, proof, args["customer_id"]))
                if not supplied_by_user(proof, state["history"]) or not matches:
                    raise ValueError("Verification mismatch")
                if state["identity"]["verified"] and body["customer_id"] != state["identity"]["customer_id"]:
                    raise ValueError("Customer switch")
            elif name == "get_order":
                if args["order_id"] not in customer_order_ids(state["customer_record"]):
                    raise ValueError("Order not in verified references")
                validate_order(body, args["customer_id"], args["order_id"])
            elif name == "list_customer_orders":
                if body.get("customer_id") != args["customer_id"] or not isinstance(body.get("orders"), list):
                    raise ValueError("Invalid owned order collection")
                own_ids = customer_order_ids(state["customer_record"])
                ids_seen = set()
                for order in body["orders"]:
                    validate_order(order, args["customer_id"], order.get("order_id") if isinstance(order, dict) else None)
                    if order["order_id"] not in own_ids or order["order_id"] in ids_seen or (args["status"] and order["status"] != args["status"]):
                        raise ValueError("Invalid order scope or status filter")
                    ids_seen.add(order["order_id"])
                if not args["status"] and ids_seen != set(own_ids):
                    raise ValueError("Incomplete order collection")
            else:
                validate_catalog(body, name, args)
            staged.append((name, args, body))
    except (ValueError, TypeError, KeyError, OverflowError):
        finish_pending(state, "unknown")
        return "mismatch", []
    for name, args, body in staged:
        if name in {"lookup_customer", "verify_customer", "read_customer_profile"}:
            state["identity"] = {"verified": True, "customer_id": body["customer_id"]}
            state["customer_id"] = body["customer_id"]
            state["customer_record"] = body
            if state.get("identity_evidence") is None:
                state["identity_evidence"] = {"inputs": {k: args.get(k, "") for k in PROOF_FIELDS}, "verified_at_turn": state["turn"], "source": "user_input_and_matched_search_profile"}
    finish_pending(state, "succeeded")
    return "succeeded", staged


def read_intent(text: str):
    """Conservative explicit-ID routing; ambiguous descriptions ask for clarification."""
    for name, field, pattern in (("get_order", "order_id", r"(?:order[_ ]id|order number|订单号)\s*[:：=]\s*([^\s,;，；]+)|(?:\border|订单)\s*[:：=]?\s*(#[\w-]+)"),
                                 ("get_product", "product_id", r"(?:product[_ ]id|商品编号)\s*[:：=]\s*([\w-]+)"),
                                 ("get_item", "item_id", r"(?:item[_ ]id|变体编号)\s*[:：=]\s*([\w-]+)")):
        match = re.search(pattern, text, re.I)
        if match:
            value = next(v for v in match.groups() if v is not None)
            if field == "order_id" and value.casefold() in {"status", "details", "is", "number", "history"}:
                continue
            return name, {field: value}
    lowered = text.casefold()
    if any(v in lowered for v in ("orders", "my order", "订单")):
        status = next((s for s in sorted(ORDER_STATUSES, key=len, reverse=True) if s in lowered), "")
        return "list_customer_orders", {"status": status}
    if any(v in lowered for v in ("catalog", "products", "商品目录", "商品种类")):
        return "list_products", {}
    if any(v in lowered for v in ("profile", "payment methods", "档案", "支付方式", "默认地址")):
        return "read_customer_profile", {}
    return None


def format_reads(records):
    lines = []
    for name, _, body in records:
        if name in {"lookup_customer", "verify_customer"}:
            lines.append(customer_reply(json.dumps(body)))
        elif name == "read_customer_profile":
            lines.append("Verified customer profile: " + json.dumps(body, ensure_ascii=False))
        elif name in {"get_order", "list_customer_orders"}:
            orders = [body] if name == "get_order" else body["orders"]
            lines.append("Owned order records: " + json.dumps(orders, ensure_ascii=False))
            lines.append("Original item prices are recorded separately from catalog prices. Order dates and delivery estimates are unknown unless explicitly provided; processed does not prove a shipment date, and a tracking ID alone is not a shipment event.")
        elif name == "list_products":
            lines.append(f"Product kinds: {len(body['products'])}. " + json.dumps(body["products"], ensure_ascii=False))
        elif name == "get_product":
            items = body["items"]
            lines.append(f"Variants: {len(items)}; available variants: {sum(i['available'] for i in items)}. Current catalog prices/options: " + json.dumps(body, ensure_ascii=False))
        else:
            lines.append("Current catalog variant (not original purchase price): " + json.dumps(body, ensure_ascii=False))
    return "\n".join(lines)


def advance(turn: TurnInput, state: dict, model_adapter=None):
    from support_agent.state import clone_state, finish_pending, result_history
    state = clone_state(state)
    state["turn"] += 1
    from support_agent.handoff_session import accept_handoff_result, route_handoff, assessment as handoff_assessment, reply as handoff_reply
    if state["handoff"]["status"] in {"accepted", "unknown"}:
        if turn.kind == "user":
            state["history"].append({"role": "user", "content": turn.content})
            from support_agent.proposals import observe_user
            observe_user(state, len(state["history"]) - 1)
            state["user_request"] = turn.content
            state["tool_calls_since_user"] = state["model_calls_since_user"] = 0
        return handoff_reply(state, handoff_assessment(state["handoff"]["status"]))
    if turn.kind == "tools":
        if state["handoff"]["status"] == "dispatched":
            return accept_handoff_result(state, turn.outcomes)
        from support_agent.workflow_boundary import WorkflowBoundary
        from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES
        # Ignore any abandoned preparation before choosing the active kind;
        # a late foreign result cannot invalidate a newer cancellation batch.
        for kind in WORKFLOW_KINDS:
            abandoned = {e[kind + "_abandoned"]["call_id"] for e in state["history"] if kind + "_abandoned" in e}
            if turn.outcomes and all(o.id in abandoned for o in turn.outcomes):
                return WorkflowBoundary(kind, MAX_WORKFLOW_RESULT_BYTES).accept(state, turn.outcomes)
        for kind in WORKFLOW_KINDS:
            if state[kind + "_pending"] is not None:
                return WorkflowBoundary(kind, MAX_WORKFLOW_RESULT_BYTES).accept(state, turn.outcomes)
        status, records = consume_results(state, turn.outcomes)
        state["history"].append(result_history(turn.outcomes, status=status))
        if status != "succeeded":
            text = {"none": "No customer lookup or read is pending.", "unknown": "The customer lookup/read result was missing or ambiguous. Please try again.",
                    "failed": "I could not verify or read the requested records because the lookup failed. Please check the details or try again.",
                    "mismatch": "The customer lookup/read did not match the verification details or authorized scope."}[status]
            return reply(state, text)
        if len(records) == 1 and records[0][0] in {"lookup_customer", "verify_customer"}:
            from support_agent.returns_session import route_returns
            returns = route_returns(state)
            if returns is not None:
                return returns
            from support_agent.items_session import route_items
            items = route_items(state)
            if items is not None:
                return items
            from support_agent.cancellation_session import route_cancellation
            cancellation = route_cancellation(state)
            if cancellation is not None:
                return cancellation
            from support_agent.payment_session import route_payment
            payment = route_payment(state)
            if payment is not None:
                return payment
            from support_agent.address_session import route_address
            address = route_address(state)
            if address is not None:
                return address
            intent = read_intent(state["user_request"])
            if intent:
                try:
                    return emit(state, *intent)
                except (InvalidAction, ValueError):
                    return reply(state, "I cannot read that order outside your verified references. Please provide an order ID from your own profile.")
        return reply(state, format_reads(records))

    text = turn.content if isinstance(turn.content, str) else ""
    if state["cancellation_pending"] is not None and state["cancellation_pending"]["mode"] == "prepare":
        from support_agent.cancellation_session import _boundary
        _boundary().event(state, "cancellation_abandoned", {"call_id": state["cancellation_pending"]["call_id"]})
    if state["items_pending"] is not None and state["items_pending"]["mode"] == "prepare":
        from support_agent.items_session import _boundary
        _boundary().event(state, "items_abandoned", {"call_id": state["items_pending"]["call_id"]})
    if state["returns_pending"] is not None and state["returns_pending"]["mode"] == "prepare":
        from support_agent.returns_session import _boundary
        _boundary().event(state, "returns_abandoned", {"call_id": state["returns_pending"]["call_id"]})
    finish_pending(state, "unknown")
    if state["payment_pending"] is not None and state["payment_pending"]["mode"] == "prepare":
        from support_agent.payment_session import _boundary
        _boundary().event(state, "payment_abandoned", {"call_id":state["payment_pending"]["call_id"]})
    if state["address_pending"] is not None and state["address_pending"]["mode"] == "prepare":
        from support_agent.address_session import _event
        _event(state, "address_abandoned", {"call_id": state["address_pending"]["call_id"]})
    from support_agent.handoff_session import intent as handoff_intent
    if handoff_intent(text) == "request":
        from support_agent.workflow_boundary import WorkflowBoundary
        from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES
        for kind in WORKFLOW_KINDS:
            pending = state[kind + "_pending"]
            if pending is not None and pending["mode"] == "execute" and pending["status"] == "pending":
                WorkflowBoundary(kind, MAX_WORKFLOW_RESULT_BYTES).event(state, kind + "_unknown", {"call_id": pending["call_id"]})
    state["history"].append({"role": "user", "content": text})
    from support_agent.proposals import observe_user
    proposal_reply = observe_user(state, len(state["history"]) - 1)
    state["user_request"] = text
    state["tool_calls_since_user"] = 0
    state["model_calls_since_user"] = 0
    handoff = route_handoff(state, text)
    if handoff is not None:
        return handoff
    claim = find_customer_id(text)
    proof = proof_from_text(text)
    if state["identity"]["verified"]:
        evidence = state.get("identity_evidence")
        if (claim and claim != state["identity"]["customer_id"]) or (proof and evidence and any(normalized(proof[k]) != normalized(evidence["inputs"][k]) for k in PROOF_FIELDS)):
            return reply(state, "I cannot switch to another customer's account or verification details in this session.")
    else:
        state["customer_id"] = claim or state["customer_id"]
        fields = fields_from_text(text)
        if fields:
            if "email" in fields:
                state["verification_draft"] = {"email": fields["email"]}
            else:
                state["verification_draft"].pop("email", None)
                state["verification_draft"].update(fields)
            try:
                proof = verification_inputs(**state["verification_draft"])
            except ValueError:
                proof = None
    if state["returns_pending"] is not None:
        from support_agent.returns_session import route_returns
        return route_returns(state, text)
    if state["items_pending"] is not None:
        from support_agent.items_session import route_items
        return route_items(state, text)
    if state["cancellation_pending"] is not None:
        from support_agent.cancellation_session import route_cancellation
        return route_cancellation(state, text)
    if state["address_pending"] is not None:
        from support_agent.address_session import route_address
        return route_address(state, text)
    if state["payment_pending"] is not None:
        from support_agent.payment_session import route_payment
        return route_payment(state, text)
    if proof:
        name = "lookup_customer" if proof["email"] else "verify_customer"
        args = {"customer_id": state["customer_id"] or "", "email": proof["email"]} if name == "lookup_customer" else {"customer_id": state["customer_id"] or "", **proof}
        return emit(state, name, args)
    if not state["identity"]["verified"] or not state.get("identity_evidence"):
        return reply(state, "Please provide your email, or first name, last name and postal code, to verify identity before I access your profile. A customer ID alone is not verification.")
    from support_agent.returns_session import route_returns
    returns = route_returns(state, text)
    if returns is not None:
        return returns
    from support_agent.items_session import route_items
    items = route_items(state, text)
    if items is not None:
        return items
    from support_agent.cancellation_session import route_cancellation
    cancellation = route_cancellation(state, text)
    if cancellation is not None:
        return cancellation
    from support_agent.payment_session import route_payment
    payment = route_payment(state, text)
    if payment is not None:
        return payment
    from support_agent.address_session import route_address
    address = route_address(state, text)
    if address is not None:
        return address
    if proposal_reply is not None:
        if proposal_reply["kind"] == "set_ack":
            from support_agent.proposals import record_set_ack
            return record_set_ack(state)
        if proposal_reply["kind"] == "ack":
            from support_agent.proposals import record_ack
            return record_ack(state, proposal_reply["text"])
        return reply(state, proposal_reply["text"])
    intent = read_intent(text)
    if intent:
        try:
            return emit(state, *intent)
        except (InvalidAction, ValueError):
            return reply(state, "I cannot access that order outside your own verified references. Please clarify your order ID.")
    if model_adapter is not None:
        try:
            if state["model_calls_since_user"] >= MAX_MODEL_CALLS_PER_REQUEST:
                raise InvalidAction("Model budget exhausted")
            state["model_calls_since_user"] += 1
            decision = model_adapter.decide(state)
            usage = getattr(model_adapter, "last_usage", None)
            if usage is not None:
                state["model_usage"].append({"turn": state["turn"], **usage})
            if decision.calls:
                record_decision(state, decision)
                return decision, state
            return reply(state, decision.text)
        except Exception:
            # No transport/SDK exception or unverified output is shown to a customer.
            return reply(state, "I cannot safely interpret that request. Please specify a profile, order ID, product ID or item ID to read.")
    return reply(state, "Please specify your own order ID, a product ID, an item ID, a profile/catalog query, an address change, a saved-method payment switch or an owned-order cancellation. Other business changes need a separate workflow; I cannot infer missing dates or account facts.")
