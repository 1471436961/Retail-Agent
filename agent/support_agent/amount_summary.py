"""Read-only cross-order evidence; never a settlement or consent authority.

One latest accepted order snapshot contributes visible rows once. Equal rows in
that snapshot still represent separate occurrences. Receipts are not additional
transactions. Quotes retain their action-specific arithmetic and source prefix.
"""
import json
import re
from decimal import Decimal, localcontext

from support_agent.adapters.read_api import customer_order_ids, MAX_ORDERS_PER_LIST
from support_agent.domain.catalog import return_refund_basis
from support_agent.domain.money import display_exact_amount, finite_number, price_difference
from support_agent.domain.policies import _payments
from support_agent.domain.rules import allow, deny, input_error, need


def exact_sum(values):
    with localcontext() as context:
        context.prec = 700 + len(str(len(values)))
        return str(sum((v if isinstance(v, Decimal) else Decimal(str(finite_number(v))) for v in values), Decimal(0)))


def _order_snapshots(state):
    calls, orders, sources = {}, {}, {}
    statuses = {o['call_id']: o['status'] for o in state['operations'] if not o['mutates']}
    for index, entry in enumerate(state['history']):
        calls.update({c['id']: c for c in entry.get('tool_calls', [])})
        for call in entry.get('tool_calls', []):
            if call['name'] in {'get_order', 'list_customer_orders'} and statuses.get(call['id']) != 'succeeded':
                ids = [call['arguments']['order_id']] if call['name'] == 'get_order' else customer_order_ids(state['customer_record'])
                for oid in ids:
                    orders.pop(oid, None); sources.pop(oid, None)
        results = entry.get('tool_messages', []) if entry['role'] == 'tools' else [entry] if entry['role'] == 'tool' else []
        for result in results:
            call = calls.get(result['id'])
            if not call or call['name'] not in {'get_order', 'list_customer_orders'}:
                continue
            ids = [call['arguments']['order_id']] if call['name'] == 'get_order' else customer_order_ids(state['customer_record'])
            if statuses.get(result['id']) != 'succeeded' or result['error']:
                # A later unsuccessful attempt invalidates earlier freshness.
                for oid in ids:
                    orders.pop(oid, None); sources.pop(oid, None)
                continue
            body = json.loads(result['content'])
            if call['name'] == 'list_customer_orders':
                for oid in ids:
                    orders.pop(oid, None); sources.pop(oid, None)
            for order in body['orders'] if call['name'] == 'list_customer_orders' else [body]:
                orders[order['order_id']] = order
                sources[order['order_id']] = {'history_index': index, 'call_id': result['id']}
    return orders, sources


def _summarize_amounts(state, order_ids):
    """Structured accepted-evidence summary, with separate category totals.

The order of IDs is the user-selected order for difference communication only;
it never changes the order or amount of backend submissions. No arrival source
exists in the public schema, so arrival stays unknown, including after success.
"""
    from support_agent.proposals import _current_records, _scope_facts
    if (not isinstance(order_ids, list) or not order_ids
            or any(not isinstance(v, str) or not v.strip() for v in order_ids)
            or len(set(order_ids)) != len(order_ids)):
        return input_error('invalid_summary_orders', 'Select each exact order ID once.', 'U3')
    if not state['identity']['verified'] or not state['identity_evidence']:
        return need('summary_identity_required', 'Verify identity before summarizing private orders.', 'ID-01')
    if state['handoff']['status'] not in {'not_requested', 'rejected'}:
        return need('summary_handoff_blocks_reads', 'Human transfer blocks further processing.', 'H-01')
    from support_agent.workflow_registry import WORKFLOW_KINDS
    if state['pending_calls'] or any(state[k + '_pending'] is not None for k in WORKFLOW_KINDS):
        return need('summary_evidence_unresolved', 'A dispatched result is unresolved; no summary is asserted.', 'W-01')
    if not set(order_ids) <= set(customer_order_ids(state['customer_record'])):
        return deny('summary_order_not_owned', 'Every selected order must be in your verified references.', 'ID-02')
    orders, sources = _order_snapshots(state)
    if any(oid not in orders for oid in order_ids):
        return need('summary_order_read_required', 'Refresh every selected owned order; missing or failed reads are not zero amounts.', 'U3')

    # An attempted version contributes once from its journal, never again from
    # a proposal/receipt. Definite failures do not enter an intended total.
    writes = [o for o in state['operations'] if o['mutates']]
    attempted = {o['version'] for o in writes}
    evidence = [(o['spec'], 'persistence_unresolved' if o['persistence_unresolved'] else o['status'], o['sent_index'], o['version']) for o in writes
                if o['status'] != 'failed']
    evidence += [(p['spec'], p['status'], p['presentation_index'], p['version'])
                 for p in _current_records(state) if p['version'] not in attempted and p['status'] in {'proposed', 'confirmed'}]
    by_scope = {}
    for candidate in evidence:
        key = (candidate[0]['action'], candidate[0]['target'].get('order_id'))
        if key not in by_scope or candidate[1] in {'sent', 'unknown', 'acknowledged', 'succeeded', 'persistence_unresolved'}:
            by_scope[key] = candidate
    evidence = list(by_scope.values())
    rows, differences, estimates, charges, refunds = [], [], [], [], []
    for oid in order_ids:
        order = orders[oid]
        row = {'order_id': oid, 'source': sources[oid], 'order_status': order['status'],
               'original_item_price_sum': exact_sum([i['price'] for i in order['items']]),
               'visible_refunds': [], 'quotes': []}
        for payment_index, payment in enumerate(_payments(order['payments'])):
            if payment['transaction_type'] == 'refund':
                row['visible_refunds'].append({**payment, 'payment_index': payment_index})
                refunds.append(payment['amount'])
        for spec, status, index, version in evidence:
            if spec['target'].get('order_id') != oid:
                continue
            action = spec['action']
            if action not in {'modify_items', 'exchange', 'return', 'cancel'}:
                continue
            quote = {'action': action, 'version': version, 'status': status,
                     'source_index': index, 'settlement_verified': False}
            if action in {'modify_items', 'exchange'}:
                quote['signed_difference'] = spec['amount']['value']
                differences.append(quote['signed_difference'])
            elif action == 'return':
                before = _scope_facts(state['history'][:index], spec)['order']
                basis = return_refund_basis(before['items'], spec['parameters']['item_ids'])
                if basis['decision'] != 'allow':
                    return need('summary_quote_unavailable', 'The selected original-price basis is unavailable.', 'U3')
                quote.update({k: basis['details'][k] for k in ('item_ids', 'exact_price_sum', 'aggregate_amount', 'amount_is_estimate', 'estimate_method')})
                estimates.append(quote)
            else:
                quote['original_charges'] = spec['amount']['rows']
                quote['original_charge_sum'] = exact_sum([p['amount'] for p in spec['amount']['rows']])
                charges.extend(p['amount'] for p in spec['amount']['rows'])
            row['quotes'].append(quote)
        rows.append(row)
    return allow('order_amount_summary', 'Amounts are separated by evidence type; none proves settlement or arrival.', 'MO-01', 'RF-01', 'U6',
        details={'orders': rows, 'write_authorized': False,
                 'differences': {'per_order_values': differences, 'evidence_count': len(differences), 'signed_total': price_difference([(0, v) for v in differences]) if differences else None, 'method': 'ordered_float_sum_final_round_2_communication_only'},
                 'return_estimates': {'evidence_count': len(estimates), 'exact_original_price_sum': exact_sum([Decimal(q['exact_price_sum']) for q in estimates]) if estimates else None,
                                     'display_estimate_total': exact_sum([q['aggregate_amount'] for q in estimates]) if estimates else None,
                                     'method': 'exact_sum_of_per_order_half_up_display_estimates', 'amount_is_estimate': True},
                 'cancellation_original_charges': {'evidence_count': len(charges), 'total': exact_sum(charges) if charges else None, 'method': 'exact_decimal_sum_no_rounding_not_net_balance'},
                 'visible_refunds': {'total': exact_sum(refunds) if refunds else None, 'row_count': len(refunds), 'method': 'one_latest_snapshot_per_order_preserve_row_occurrences'},
                 'arrival': {'amount': None, 'status': 'unknown'}, 'settlement_verified': False})


def summarize_amounts(state, order_ids):
    from support_agent.state import clone_state
    state = clone_state(state)
    try:
        return _summarize_amounts(state, order_ids)
    except (TypeError, ValueError, KeyError, ArithmeticError):
        return need('summary_amount_unavailable', 'Accepted amount evidence cannot be safely summarized; no amount is guessed.', 'MO-01', 'U3')


def summary_request(text):
    match = re.fullmatch(r'(?:Summarize order amounts|汇总订单金额)\s*[:：]?\s*(#[\w-]+(?:[\s,，]+#[\w-]+)*)[.!。！]?', text.strip(), re.I)
    return list(dict.fromkeys(re.findall(r'#[\w-]+', match[1]))) if match else None


def render_summary(result):
    if result['decision'] != 'allow':
        return result['message']
    data = result['details']
    lines = ['Order amount summary:']
    for row in data['orders']:
        lines.append(f"{row['order_id']}: {row['order_status']}; original item prices total {display_exact_amount(row['original_item_price_sum'])}.")
        for quote in row['quotes']:
            if quote['action'] == 'return':
                lines.append(f"  Return estimate {quote['aggregate_amount']:.2f} for selected units {', '.join(quote['item_ids'])}; exact original-price sum {quote['exact_price_sum']}. Application result: {quote['status']}; no settlement proof.")
            elif quote['action'] in {'exchange', 'modify_items'}:
                lines.append(f"  Signed difference {quote['signed_difference']:.2f}; application result: {quote['status']}.")
            else:
                lines.append(f"  Cancellation original charge basis {display_exact_amount(quote['original_charge_sum'])}; application result: {quote['status']}.")
    if data['differences']['per_order_values']:
        lines.append(f"Signed differences total: {data['differences']['signed_total']:.2f} (communication only; separate backend operations).")
    if any(q['action'] == 'return' for row in data['orders'] for q in row['quotes']):
        lines.append(f"Return display estimates total: {display_exact_amount(data['return_estimates']['display_estimate_total'])}; exact selected original prices: {data['return_estimates']['exact_original_price_sum']}.")
    if any(q['action'] == 'cancel' for row in data['orders'] for q in row['quotes']):
        lines.append('Cancellation original charges total: ' + display_exact_amount(data['cancellation_original_charges']['total']) + ' (not a net balance).')
    visible = data['visible_refunds']
    lines.append('Visible recorded refunds: ' + (display_exact_amount(visible['total']) + f" ({visible['row_count']} rows)." if visible['total'] is not None else 'unknown; no visible refund row, not assumed zero.'))
    lines.append('Refund arrival: unknown. Visible transactions and estimates do not prove refund arrival. No combined backend charge/refund was sent.')
    return '\n'.join(lines)


def route_summary(state, *, after_reads=False, order_ids=None):
    """Finite explicit default read route; refresh via the existing owned API."""
    from support_agent.read_session import reply, emit
    ids = summary_request(state['user_request']) if order_ids is None else order_ids
    if ids is None:
        return None
    if set(ids) <= set(customer_order_ids(state['customer_record'])):
        plan = summary_refresh_rule(state, ids, after_reads=after_reads)
        if plan['decision'] != 'allow':
            return reply(state, plan['message'])
        if plan['details'].get('tool'):
            return emit(state, plan['details']['tool'], plan['details']['arguments'])
    result = summarize_amounts(state, ids)
    return reply(state, render_summary(result))


def summary_refresh_rule(state, ids, *, after_reads=False):
    """Choose existing read tools; a large profile need not force a list read.

    Only successful get_order calls after this actual user request satisfy the
    fallback. Old snapshots cannot stand in for the current refresh sequence.
    The ordinary reducer still validates every result and applies its budget.
    """
    from support_agent.read_session import MAX_READ_CALLS_PER_REQUEST
    if len(customer_order_ids(state['customer_record'])) <= MAX_ORDERS_PER_LIST:
        return allow('summary_refresh_planned', 'Refresh the selected orders.',
                     details={} if after_reads else {'tool': 'list_customer_orders', 'arguments': {'status': ''}})
    start = next((i for i in range(len(state['history']) - 1, -1, -1) if state['history'][i]['role'] == 'user'), None)
    if start is None:
        return need('summary_actual_user_required', 'An actual user request is required before refreshing orders.', 'U3')
    successful = {o['call_id'] for o in state['operations'] if not o['mutates'] and o['status'] == 'succeeded'}
    refreshed = {c['arguments']['order_id'] for e in state['history'][start + 1:] for c in e.get('tool_calls', [])
                 if c['name'] == 'get_order' and c['id'] in successful} if after_reads else set()
    remaining = [oid for oid in ids if oid not in refreshed]
    if len(remaining) > MAX_READ_CALLS_PER_REQUEST - state['tool_calls_since_user']:
        return need('summary_read_budget_exceeded', 'Too many selected orders for one summary request. Select fewer exact order IDs or ask for human assistance; no partial summary is asserted.', 'U3')
    return allow('summary_selected_orders_refresh', 'Refresh only the selected owned orders.',
                 details={'tool': 'get_order', 'arguments': {'order_id': remaining[0]}} if remaining else {})
