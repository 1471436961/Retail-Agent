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


def capability_reply(text):
    """Explicit unsupported requests need an explanation, not account access.

    This operates only on the current real user text; business JSON cannot
    manufacture a new operation. It grants no permission for alternatives.
    """
    if '{' in text:
        return None
    if re.search(r'\b(change|update|modify)\b.{0,60}\b(email|email address)\b|修改.{0,20}(邮箱|电子邮件)', text, re.I):
        return 'Customer support cannot change your profile email. No email change has been made or arranged; there is no supported email-change API.'
    if re.search(r'\b(add|register)\b.{0,40}\b(new\s+)?(payment method|credit card|card|paypal)\b|新增支付方式|添加.{0,15}(支付方式|信用卡)', text, re.I):
        return 'Add a new payment method through the website. Customer support has no payment-method creation API and cannot use an unverified new method ID. An existing saved method may be considered in a separately confirmed supported request.'
    from support_agent.domain.payment_intake import starts_payment_request
    if (not starts_payment_request(text) and
            re.search(r'\b(split|divide)\b.{0,60}\b(two|2|multiple)\b.{0,20}\b(cards|methods)\b|分摊.{0,15}(两张卡|多张卡)|两张卡.{0,20}(分摊|混合支付)', text, re.I)):
        return 'Split or mixed payment across two cards is unsupported. A supported payment change uses one existing saved method covering the full order; no split payment has been submitted.'
    if re.search(r'\b(place|create)\b.{0,30}\b(new order|an order)\b|重新下单|代下.{0,10}订单', text, re.I):
        return 'Customer support cannot place a new order or reorder items. No purchase has been made or arranged. Product information and a separately confirmed supported existing-order request remain available.'
    if re.search(r'\b(undo|restore|reverse)\b.{0,45}\b(cancellation|cancelled order|canceled order)\b|撤销取消|恢复.{0,15}已取消订单', text, re.I):
        return 'A cancelled order cannot be restored through the supported API. No restoration, expedited delivery or new order has been made or arranged. You may request human assistance, without a guarantee of an exception.'
    if re.search(r'\b(guarantee|promise)\b.{0,60}\b(five|5)\s+days\b|保证.{0,20}[五5]天', text, re.I):
        return 'The available records do not establish a five-day processing or delivery guarantee. No expedited handling or delivery promise has been arranged. Any cancellation still needs your own allowed reason and complete confirmation.'
    if re.search(r'\b(compensate|compensation|reorder|replace lost|lost package refund)\b|丢失赔偿|丢件补发', text, re.I):
        return 'The supported API does not establish lost-package compensation, a replacement shipment or a new-order purchase. None has been arranged, and no refund or arrival is claimed. A separately confirmed supported request or human assistance remains available.'
    return None


def _purchase_amounts(order):
    """Read-only original-price and recorded-payment analysis, never settlement."""
    from support_agent.amount_summary import exact_sum
    from support_agent.domain.catalog import _selected
    from support_agent.domain.money import display_exact_amount
    def displayed_sum(values):
        return display_exact_amount(exact_sum(values))
    items = order['items']
    highest = max((item['price'] for item in items), default=None)
    expensive = [{k:item[k] for k in ('item_id','name','price')} for item in items if item['price'] == highest]
    payments = order.get('payments', [])
    charges = [row['amount'] for row in payments if row['transaction_type'] == 'payment']
    refunds = [row['amount'] for row in payments if row['transaction_type'] == 'refund']
    result = {'order_id':order['order_id'],
              'original_item_total':displayed_sum([item['price'] for item in items]) if items else None,
              'highest_original_price_units':expensive,
              'recorded_charge_total':displayed_sum(charges) if charges else None,
              'visible_refund_total':displayed_sum(refunds) if refunds else None,
              'settlement_verified':False}
    request = order.get('return_request')
    if request is not None:
        selection = _selected(items,request['item_ids'])
        if selection['decision'] == 'allow':
            from collections import Counter
            remaining = Counter(request['item_ids']); retained=[]
            for item in items:
                if remaining[item['item_id']]:remaining[item['item_id']]-=1
                else:retained.append(item)
            result['retained_original_units']=[{k:item[k] for k in ('item_id','name','price')} for item in retained]
            result['retained_original_total']=displayed_sum([item['price'] for item in retained])
        else:
            result['retained_original_units']=None;result['retained_original_total']=None
    return result


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
            lines.append('Original-price analysis (occurrences preserved; charges and visible refunds are separate, missing evidence is unknown, not zero; no settlement/arrival proof): '
                         + json.dumps([_purchase_amounts(order) for order in orders],ensure_ascii=False))
            if name == 'list_customer_orders':
                lines.append('Original purchases grouped by exact product ID (all recorded unit occurrences, not current prices or refunds): '
                             + json.dumps(_purchase_groups(orders),ensure_ascii=False))
            lines.append("Original item prices are recorded separately from catalog prices. Order dates and delivery estimates are unknown unless explicitly provided; processed does not prove a shipment date, and a tracking ID alone is not a shipment event.")
        elif name == "list_products":
            lines.append(f"Product kinds: {len(body['products'])}. " + json.dumps(body["products"], ensure_ascii=False))
        elif name == "get_product":
            items = body["items"]
            lines.append(f"Variants: {len(items)}; available variants: {sum(i['available'] for i in items)}. Current catalog prices/options: " + json.dumps(body, ensure_ascii=False))
            available = [item for item in items if item['available']]
            lowest = min((item['price'] for item in available), default=None)
            lines.append('Lowest current price among available variants (all equal-price choices retained; no purchase permission): '
                         + json.dumps({'product_id':body['product_id'],'price':lowest,
                                       'variants':[item for item in available if item['price']==lowest]},ensure_ascii=False))
        else:
            lines.append("Current catalog variant (not original purchase price): " + json.dumps(body, ensure_ascii=False))
    return "\n".join(lines)


def _purchase_groups(orders):
    from support_agent.amount_summary import exact_sum
    from support_agent.domain.money import display_exact_amount
    groups = {}
    for order in orders:
        for item in order['items']:
            row = groups.setdefault(item['product_id'], {'product_id':item['product_id'], 'units':[]})
            row['units'].append({'order_id':order['order_id'], 'item_id':item['item_id'],
                                 'name':item['name'], 'original_price':item['price']})
    for row in groups.values():
        row['unit_count'] = len(row['units'])
        row['original_price_total'] = display_exact_amount(exact_sum([i['original_price'] for i in row['units']]))
    return list(groups.values())


def route_scope_analysis(state, *, arguments=None):
    """Finite real-user, read-only estimates and same-order alternative comparison.

    Read fresh owned facts for this request only. This creates no proposal,
    confirmation, task or write permission; any later business request must
    pass its ordinary complete producer and confirmation path.
    """
    text = state['user_request']
    match = re.fullmatch(r'(Estimate selected items|Compare return and exchange)\s+order\s+(#[\w-]+)\s*:\s*(\{.*\})', text, re.I | re.S) if arguments is None else None
    if arguments is None and not match:
        return None
    from support_agent.domain.catalog import _selected, return_refund_basis, resolve_replacements
    from support_agent.domain.items_intake import criteria_for_line
    from support_agent.domain.candidate_selection import select_candidates
    from support_agent.domain.rules import identifier
    from support_agent.domain.orders import order_state_rule
    from support_agent.address_session import _accepted_bodies
    try:
        if arguments is None:
            body = json.loads(match[3]); comparison = match[1].casefold().startswith('compare')
        else:
            comparison = bool(arguments['replacements'])
            body = {'item_ids': arguments['item_ids']}
            if comparison:
                body['replacements'] = arguments['replacements']
        if not isinstance(body, dict) or set(body) != ({'item_ids', 'replacements'} if comparison else {'item_ids'}):
            raise ValueError()
        ids = body['item_ids']
        if not isinstance(ids, list) or not ids or any(not identifier(i) for i in ids):
            raise ValueError()
        replacements = body.get('replacements', [])
        if comparison and (not isinstance(replacements, list) or not replacements):
            raise ValueError()
        for row in replacements:
            if not isinstance(row, dict) or set(row) not in ({'item_id','criteria'}, {'item_id','replacement_item_id'}, {'item_id','options'}) or not identifier(row['item_id']):
                raise ValueError()
    except (TypeError, ValueError):
        return reply(state, 'scope_analysis_input_error: Use exact item IDs and supported complete replacement criteria. No operation was created.')
    oid = match[2] if arguments is None else arguments['order_id']
    if oid not in customer_order_ids(state['customer_record']):
        return reply(state, 'scope_analysis_order_not_owned: No private order read or write was requested.')
    start = max(i for i,e in enumerate(state['history']) if e['role'] == 'user')
    history = state['history'][start:]
    orders = _accepted_bodies(history, {'get_order'})
    order = next((o for o in reversed(orders) if o['order_id'] == oid), None)
    if order is None:
        try:
            return emit(state, 'get_order', {'order_id':oid})
        except InvalidAction:
            return reply(state, 'scope_analysis_read_budget_exceeded: No old snapshot replaces the required current read.')
    estimate = return_refund_basis(order['items'], ids)
    if estimate['decision'] != 'allow':
        return reply(state, 'scope_analysis_' + estimate['code'] + ': ' + estimate['message'])
    result = {'order_id':oid,'item_ids':ids,'selected_original_units':_selected(order['items'],ids)['details']['items'],
              'potential_refund_estimate':estimate['details'], 'write_authorized':False,
              'settlement_or_arrival_proven':False}
    if comparison:
        return_guard = order_state_rule(order, 'return'); exchange_guard = order_state_rule(order, 'exchange')
        if return_guard['decision'] != 'allow' or exchange_guard['decision'] != 'allow':
            return reply(state, 'scope_analysis_state_not_allowed: The requested alternatives are not both eligible; no plan or write was created.')
        originals = []
        for row in replacements:
            selected = _selected(order['items'],[row['item_id']])
            if selected['decision'] != 'allow':
                return reply(state, 'scope_analysis_' + selected['code'] + ': ' + selected['message'])
            originals.append(selected['details']['items'][0])
        catalogs = _accepted_bodies(history, {'get_product'})
        needed = list(dict.fromkeys(i['product_id'] for i in originals))
        missing = [pid for pid in needed if not any(p['product_id'] == pid for p in catalogs)]
        if state['tool_calls_since_user'] + len(missing) > MAX_READ_CALLS_PER_REQUEST:
            return reply(state, 'scope_analysis_read_budget_exceeded: The complete comparison cannot be split or guessed.')
        if missing:
            return emit(state, 'get_product', {'product_id':missing[0]})
        pairs, changes, prices = [], [], []
        for row, original in zip(replacements, originals):
            catalog = next(p for p in catalogs if p['product_id'] == original['product_id'])
            criteria = criteria_for_line({**row,'text':text,'index':start}, original)
            if criteria['decision'] != 'allow':
                return reply(state, 'scope_analysis_' + criteria['code'] + ': ' + criteria['message'])
            if 'variant' in criteria['details']:
                target = next((i for i in catalog['items'] if i['item_id'] == criteria['details']['variant']),None)
                if target is None:
                    return reply(state, 'scope_analysis_target_variant_required: No cross-product substitute was selected.')
            else:
                selected = select_candidates(order['items'], row['item_id'], [catalog], criteria['details']['criteria'])
                if selected['code'] != 'candidate_selected':
                    return reply(state, 'scope_analysis_' + selected['code'] + ': No unique complete alternative can be compared. ' + json.dumps(selected['details'],ensure_ascii=False))
                target = selected['details']['selected']
            pairs.append({'existing_item_id':row['item_id'],'replacement_item_id':target['item_id']})
            changes.append({k:v for k,v in target['options'].items() if original['options'].get(k) != v})
            prices.append({'original_item_id':row['item_id'],'original_price':original['price'],'target':target})
        resolved = resolve_replacements(order['items'],pairs,catalogs,requested_options=changes,sequential_matching=False,allow_same_variant=True)
        if resolved['decision'] != 'allow':
            return reply(state, 'scope_analysis_' + resolved['code'] + ': ' + resolved['message'])
        difference = resolved['details']['price_difference']
        from decimal import Decimal
        savings = max(Decimal(0), -Decimal(str(difference)))
        refund = Decimal(str(estimate['details']['aggregate_amount']))
        result.update(exchange_candidates=prices, exchange_signed_difference=difference,
                      exchange_savings=str(savings), mutually_exclusive_same_order=True,
                      most_saving_option='return' if refund > savings else 'exchange' if savings > refund else 'customer_choice_required')
    message = 'Read-only scope analysis: ' + json.dumps(result,ensure_ascii=False)
    message += '\nPotential amounts are not cancellations, refunds or settlement. A same-order return and exchange cannot both be submitted. Review the comparison and make a new complete business request; nothing here confirms or sends it.' if comparison else '\nThis is a potential selected-item estimate, not cancellation or return eligibility, a submitted operation or money received. Partial cancellation is unsupported; keeping the order causes no write.'
    if len(message) > 4096:
        return reply(state, 'scope_analysis_display_budget_exceeded: The complete comparison cannot be displayed here. No list is truncated or submitted; human assistance is needed.')
    return reply(state, message)


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
        from support_agent.semantic_session import enabled, after_read
        if enabled(model_adapter):
            try:
                return after_read(state, model_adapter)
            except Exception:
                return reply(state, 'I could not safely interpret the records for your request. Please clarify your goal; no additional change was sent.')
        analysis = route_scope_analysis(state) if state['identity']['verified'] else None
        if analysis is not None:
            return analysis
        if len(records) == 1 and records[0][0] in {"lookup_customer", "verify_customer"}:
            from support_agent.exchange_session import route_exchange
            exchange = route_exchange(state)
            if exchange is not None:
                return exchange
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
        from support_agent.amount_summary import route_summary
        summary = route_summary(state, after_reads=True)
        if summary is not None:
            return summary
        return reply(state, format_reads(records))

    text = turn.content if isinstance(turn.content, str) else ""
    # A new user message replaces the awaited execution-result boundary. The
    # effect may already exist; late bundles cannot settle or authorize a retry.
    from support_agent.workflow_boundary import WorkflowBoundary
    from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES
    for kind in WORKFLOW_KINDS:
        pending = state[kind + '_pending']
        if pending is not None and pending['mode'] == 'execute' and pending['status'] == 'pending':
            WorkflowBoundary(kind, MAX_WORKFLOW_RESULT_BYTES).event(state, kind + '_unknown', {'call_id': pending['call_id']})
    if state["exchange_pending"] is not None and state["exchange_pending"]["mode"] == "prepare":
        from support_agent.exchange_session import _boundary
        _boundary().event(state, "exchange_abandoned", {"call_id": state["exchange_pending"]["call_id"]})
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
    from support_agent.semantic_session import enabled, interpret
    semantic_mode = enabled(model_adapter)
    candidate, semantic_error = None, False
    state['model_calls_since_user'] = 0
    if semantic_mode:
        try:
            candidate = interpret(state, model_adapter, user_text=text)
        except Exception:
            semantic_error = True
            # A failed language step must not fall back to regex consent during
            # live observation OR history restoration. This is a host refusal
            # frame, not a claim that a model successfully interpreted the text.
            candidate = {'action': 'clarify', 'identity': {}, 'arguments': {},
                         'sources': [], 'message': 'Language understanding unavailable; no authorization inferred.'}
    state["history"].append({"role": "user", "content": text})
    if candidate is not None:
        from support_agent.semantics import annotate
        annotate(state['history'], len(state['history']) - 1, candidate)
    from support_agent.proposals import observe_user
    proposal_reply = observe_user(state, len(state["history"]) - 1)
    state["user_request"] = text
    state["tool_calls_since_user"] = 0
    if not semantic_mode:
        state["model_calls_since_user"] = 0
    if semantic_error and not any(state[k + '_pending'] is not None for k in WORKFLOW_KINDS):
        return reply(state, 'Language understanding is unavailable for this request. I will not guess identity or business parameters. Please try again later or request human assistance.')
    handoff = route_handoff(state, text)
    if handoff is not None:
        return handoff
    claim = find_customer_id(text) if not semantic_mode else None
    proof = proof_from_text(text) if not semantic_mode else None
    if state["identity"]["verified"]:
        evidence = state.get("identity_evidence")
        if (claim and claim != state["identity"]["customer_id"]) or (proof and evidence and any(normalized(proof[k]) != normalized(evidence["inputs"][k]) for k in PROOF_FIELDS)):
            return reply(state, "I cannot switch to another customer's account or verification details in this session.")
    else:
        state["customer_id"] = claim or state["customer_id"]
        from support_agent.semantics import identity_fields
        fields = identity_fields(state['history'][-1])
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
    if state["exchange_pending"] is not None:
        from support_agent.exchange_session import route_exchange
        return route_exchange(state, text)
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
    limitation = capability_reply(text) if not semantic_mode else None
    if limitation is not None:
        return reply(state, limitation)
    if proof:
        name = "lookup_customer" if proof["email"] else "verify_customer"
        args = {"customer_id": state["customer_id"] or "", "email": proof["email"]} if name == "lookup_customer" else {"customer_id": state["customer_id"] or "", **proof}
        return emit(state, name, args)
    if candidate is not None:
        from support_agent.semantic_session import route
        if state['identity']['verified'] and state.get('identity_evidence') and any(
                normalized(value) != normalized(state['identity_evidence']['inputs'][key])
                for key, value in candidate['identity'].items()):
            return reply(state, 'I cannot switch verification details or customer accounts within this session.')
        try:
            return route(state, candidate, proposal_reply=proposal_reply)
        except (InvalidAction, ValueError, TypeError, KeyError):
            return reply(state, 'Those parameters could not be validated for your verified records. Please clarify the requested target or choice; no operation was sent.')
    if not state["identity"]["verified"] or not state.get("identity_evidence"):
        return reply(state, "Please provide your email, or first name, last name and postal code, to verify identity before I access your profile. A customer ID alone is not verification.")
    analysis = route_scope_analysis(state)
    if analysis is not None:
        return analysis
    from support_agent.amount_summary import route_summary
    summary = route_summary(state)
    if summary is not None:
        return summary
    from support_agent.exchange_session import route_exchange
    exchange = route_exchange(state, text)
    if exchange is not None:
        return exchange
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
