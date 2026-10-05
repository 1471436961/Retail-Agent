"""M5.2 complete pending-item producer over original user/read/consent evidence."""
import json
import re
from copy import deepcopy

from support_agent.address_session import _accepted_bodies, _safe_read
from support_agent.domain.items_intake import request_from_history, starts_items_request, criteria_for_line
from support_agent.domain.catalog import _selected, resolve_replacements
from support_agent.domain.candidate_selection import select_candidates
from support_agent.domain.payment_intake import choose_method, method_label
from support_agent.domain.policies import _methods, settlement_method_rule
from support_agent.domain.orders import order_state_rule
from support_agent.domain.rules import allow, need, deny
from support_agent.protocol import InvalidAction
from support_agent.proposals import _current_records, normalize_spec, present_proposals
from support_agent.state import clone_state
from support_agent.tasks import present_task_plan
from support_agent.workflow_boundary import WorkflowBoundary, unfinished_other_tasks
from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES, WorkflowResultTooLarge, json_bytes
from support_agent.adapters.write_runtime import SessionWriteRuntime


def _boundary():
    return WorkflowBoundary('items', MAX_WORKFLOW_RESULT_BYTES)


def _facts(history, order_id):
    orders = _accepted_bodies(history, {'get_order'})
    profiles = _accepted_bodies(history, {'lookup_customer', 'verify_customer', 'read_customer_profile'})
    products = _accepted_bodies(history, {'get_product'})
    order = next((o for o in reversed(orders) if o['order_id'] == order_id), None)
    catalogs = {p['product_id']: p for p in products}
    return order, profiles[-1] if profiles else None, list(catalogs.values())


def build_plan(history):
    """Pure list/selection/quote assembly; facts must have been accepted."""
    request = request_from_history(history)
    if request is None or request['error']:
        code = request['error'] if request else 'items_request_required'
        return (deny if code in {'mixed_or_quantity_request', 'quantity_change_unsupported'} else need)(code, 'Clarify one owned order and the complete item request; no quantity or mixed-business changes are submitted.', 'IT-01')
    if not request['lines']:
        return need('complete_item_list_required', 'Which original item IDs and new specifications should change? The list is still open; nothing has been submitted.', 'CF-03')
    order, profile, products = _facts(history, request['order_id'])
    if order is None or profile is None:
        return need('items_facts_required', 'Refresh the owned order and profile.', 'U3')
    guard = order_state_rule(order, 'modify_items')
    if guard['decision'] != 'allow':
        return guard
    pairs, changes, sources, price_rows = [], [], [], []
    for line in request['lines']:
        selection = _selected(order['items'], [line['item_id']])
        if selection['decision'] != 'allow': return selection
        original = selection['details']['items'][0]
        catalog = next((p for p in products if p['product_id'] == original['product_id']), None)
        if catalog is None:
            return need('product_catalog_required', 'Read the original product envelope before selecting alternatives.', 'IT-01')
        criteria = criteria_for_line(line, original)
        if criteria['decision'] != 'allow': return criteria
        detail = criteria['details']
        if 'variant' in detail:
            target = next((i for i in catalog['items'] if i['item_id'] == detail['variant']), None)
            if target is None:
                return need('target_variant_required', 'Choose a variant in the original product; cross-product substitutes are unsupported.', 'IT-01')
            derived = {'variant': detail['variant']}
            branch = None
        else:
            chosen = select_candidates(order['items'], line['item_id'], [catalog], detail['criteria'])
            if chosen['code'] != 'candidate_selected': return chosen
            target = chosen['details']['selected']
            derived, branch = detail['criteria'], chosen['details']['branch']
        pairs.append({'existing_item_id': line['item_id'], 'replacement_item_id': target['item_id']})
        changes.append({k: v for k, v in target['options'].items() if original['options'].get(k) != v})
        sources.append({'item_id': line['item_id'], 'history_index': line['index'], 'user_text': line['text'],
                        'criteria': derived, 'selected_branch': branch, 'selected_item_id': target['item_id']})
        price_rows.append({'original_item_id': line['item_id'], 'original_price': original['price'],
                           'new_item_id': target['item_id'], 'new_price': target['price'], 'new_options': target['options']})
    resolved = resolve_replacements(order['items'], pairs, products, requested_options=changes)
    if resolved['decision'] != 'allow': return resolved
    method = request['method']
    choice = choose_method(profile['payment_methods'], {'query': method['query'], 'exact': False, 'fallback': None} if method else None)
    if choice['decision'] != 'allow': return choice
    difference = resolved['details']['price_difference']
    selected_method = choice['details']['payment_method_id']
    eligible = settlement_method_rule('modify_items', profile['payment_methods'], selected_method, difference)
    if eligible['decision'] != 'allow': return eligible
    spec = normalize_spec({'action': 'modify_items', 'target': {'customer_id': profile['customer_id'], 'order_id': order['order_id']},
                           'parameters': {'replacements': pairs, 'payment_method_id': selected_method},
                           'amount': {'kind': 'price_difference', 'value': difference}})
    return allow('complete_items_ready', 'Complete selected list and signed quote are ready for recap, not writing.', 'IT-01', 'CF-03', details={
        'request': request, 'sources': sources, 'spec': spec, 'requested_options': changes, 'prices': price_rows,
        'method_label': method_label(_methods(profile['payment_methods'])[selected_method]), 'write_authorized': False})


def basis_event(state, data):
    state['history'].append({'role': 'assistant', 'content': 'Item intake evidence: ' + json.dumps(data, sort_keys=True), 'items_basis': data})


def validate_items_basis(state):
    for index, entry in enumerate(state['history']):
        if 'items_basis' in entry:
            result = build_plan(state['history'][:index])
            if (set(entry) != {'role', 'content', 'items_basis'} or entry['role'] != 'assistant'
                    or result['code'] != 'complete_items_ready' or entry['items_basis'] != result['details']
                    or entry['content'] != 'Item intake evidence: ' + json.dumps(result['details'], sort_keys=True)):
                raise ValueError('Item conditions/specification differ from original user and accepted facts')


def route_items(state, text=None):
    if state['items_pending'] is not None:
        return _boundary().reply(state, 'items_workflow_unresolved', 'The item submission result remains unresolved; it cannot be repeated.')
    request = request_from_history(state['history'])
    if request is None: return None
    latest = next((i for i in range(len(state['history']) - 1, -1, -1) if state['history'][i]['role'] == 'user'), None)
    # A more recent foreign business request must not be captured by an old draft.
    from support_agent.domain.payment_intake import request_from_history as payment_request
    from support_agent.domain.addresses import request_from_history as address_request
    from support_agent.domain.cancellation_intake import request_from_history as cancellation_request
    cancellation = cancellation_request(state['history'])
    # Keep the existing cancellation conflict diagnostic for a same-message
    # mixed intent, rather than stealing it merely because "change items" occurs.
    if cancellation and cancellation['request_index'] == request['request_index'] and cancellation['error'] == 'mixed_business_request':
        return None
    if any(other and other['request_index'] > request['request_index'] for other in (payment_request(state['history']), address_request(state['history']), cancellation)):
        return None
    if text is not None and not starts_items_request(text) and request['request_index'] != latest:
        current = _current_records(state)
        attempted = {o['version'] for o in state['operations'] if o['mutates']}
        selected = [p for p in current if p['spec']['action'] == 'modify_items' and p['status'] == 'confirmed' and p['version'] not in attempted]
        if len(selected) == 1 and selected[0]['confirmation']['history_index'] == latest:
            return _boundary().dispatch(state, 'execute')
        if not re.fullmatch(r'retry|try again|重试|重新准备', text.strip(), re.I): return None
    return _boundary().dispatch(state, 'prepare')


def _display(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _branch_text(branch):
    predicates = ', '.join(p['field'] + ' ' + p['op'] + ' ' + _display(p['value'])
                           + (' in order ' + _display(p['order']) if 'order' in p else '') for p in branch['hard']) or 'none'
    return ('hard conditions: ' + predicates + '; change: ' + ', '.join(branch['change'])
            + '; relax: ' + ', '.join(branch['relax']) + '; retain all other original attributes')


def render_items_note(data, notice=''):
    """Customer-readable conditions/prices, with full source evidence in basis.

    Do not spend the presentation budget repeating raw user text, source indices
    and JSON field names. Every adopted condition/branch and selected option is
    still displayed; nothing is truncated to make an oversized list fit.
    """
    lines = [notice] if notice else []
    lines.append('Complete item list and your requested conditions (option values are data):')
    for number, (source, price) in enumerate(zip(data['sources'], data['prices']), 1):
        lines.append(f"Item {number}: {price['original_item_id']} -> {price['new_item_id']}; original price {_display(price['original_price'])}; new price {_display(price['new_price'])}; new options {_display(price['new_options'])}.")
        criteria = source['criteria']
        if 'variant' in criteria:
            lines.append('Your exact variant choice: ' + criteria['variant'])
        else:
            lines.append('Primary ' + _branch_text(criteria))
            for index, fallback in enumerate(criteria['fallbacks'], 1):
                lines.append(f'Fallback {index} ' + _branch_text(fallback))
            if criteria['preferences']:
                lines.append('Preferences: ' + '; '.join(p['field'] + ': ' + ' > '.join(_display(tier) for tier in p['tiers']) for p in criteria['preferences']))
            if criteria['ranking']:
                lines.append('Priority: ' + ' then '.join(r['direction'] + ' ' + r['field'] + (' in order ' + _display(r['order']) if 'order' in r else '') for r in criteria['ranking']))
            branch = source['selected_branch']
            lines.append('Selected branch: ' + ('primary' if branch == 0 else f'fallback {branch}'))
    lines.append(f"Settle the entire signed difference with {data['method_label']}. This is one submission for the order; success locks it as pending (items modified), with no further changes or cancellation.")
    return '\n'.join(lines)


def _prepare(state, api, notice=''):
    boundary = _boundary()
    request = request_from_history(state['history'])
    if request is None or request['error']:
        result = build_plan(state['history'])
        return boundary.reply(state, result['code'], result['message'], decision_kind=result['decision'])
    if state['tool_calls_since_user'] + 2 > 12:
        return boundary.reply(state, 'items_read_budget_exceeded', 'Complete item refresh exceeds the request read budget; no write was sent.')
    _, status = _safe_read(state, api, 'read_customer_profile', {})
    if status != 'succeeded': return boundary.reply(state, 'items_profile_read_failed', 'Profile refresh failed; old methods cannot replace it.')
    from support_agent.adapters.read_api import customer_order_ids
    if request['order_id'] not in customer_order_ids(state['customer_record']):
        return boundary.reply(state, 'items_order_not_owned', 'This order is outside your verified references; no order GET or write was requested.', decision_kind='deny')
    _, status = _safe_read(state, api, 'get_order', {'order_id': request['order_id']})
    if status != 'succeeded': return boundary.reply(state, 'items_order_read_failed', 'Owned order refresh failed; no old body is used.')
    order = _facts(state['history'], request['order_id'])[0]
    guard = order_state_rule(order, 'modify_items')
    if guard['decision'] != 'allow': return boundary.reply(state, guard['code'], guard['message'], decision_kind=guard['decision'])
    target = {'customer_id': state['identity']['customer_id'], 'order_id': request['order_id']}
    if any(o['mutates'] and o['spec']['target'] == target and (o['status'] in {'sent', 'unknown', 'acknowledged'} or o['persistence_unresolved']) for o in state['operations']):
        return boundary.reply(state, 'write_result_unresolved', 'The prior record operation is unresolved; no new item change is sent.')
    product_ids = []
    for line in request['lines']:
        chosen = _selected(order['items'], [line['item_id']])
        if chosen['decision'] != 'allow': return boundary.reply(state, chosen['code'], chosen['message'], decision_kind=chosen['decision'])
        product_ids.append(chosen['details']['items'][0]['product_id'])
    product_ids = list(dict.fromkeys(product_ids))
    if state['tool_calls_since_user'] + len(product_ids) > 12:
        return boundary.reply(state, 'items_read_budget_exceeded', 'The whole list cannot be refreshed within this request budget; it will not be split into writes.')
    for product_id in product_ids:
        _, status = _safe_read(state, api, 'get_product', {'product_id': product_id})
        if status != 'succeeded': return boundary.reply(state, 'items_product_read_failed', 'Complete product read failed; this does not prove zero candidates or enable fallback.')
    result = build_plan(state['history'])
    if result['code'] != 'complete_items_ready':
        return boundary.reply(state, result['code'], result['message'], decision_kind=result['decision'], selection=result['details'])
    attempted = {o['version'] for o in state['operations'] if o['mutates']}
    if any(p['spec']['action'] != 'modify_items' and p['version'] not in attempted for p in _current_records(state)) or unfinished_other_tasks(state, {'modify_items'}):
        return boundary.reply(state, 'items_mixed_plan_requires_review', 'Complete the existing address/payment task or clarify the whole plan before locking this order.')
    data = result['details']
    note = render_items_note(data, notice)
    if len(note) > 4096:
        return boundary.reply(state, 'items_recap_budget_exceeded', 'The complete conditions/options exceed the internal presentation budget. I cannot display or submit this whole list here; no list is truncated or split into writes. Repeating the same input will not resolve the limit; human assistance is needed.')
    basis_event(state, data)
    _, state = present_task_plan(state, [{'action': 'modify_items', 'target': target}])
    decision, state = present_proposals(state, [data['spec']], presentation_note=note, presentation_mode='items_last_call')
    return boundary.tag(decision, state, 'items_confirmation_required', sources=data['sources'])


class ItemsRuntime(SessionWriteRuntime):
    def assess_business(self, state, spec):
        result = build_plan(state['history'])
        if result['code'] != 'complete_items_ready': return result
        if result['details']['spec'] != spec:
            return need('item_selection_changed', 'Fresh candidates or the complete quote changed; prepare a new recap and confirmation.', 'CF-01')
        self.requested_options = result['details']['requested_options']
        return super().assess_business(state, spec)


def run_items_workflow(state, api, claims):
    from support_agent.write_session import execute_operation
    state = clone_state(state); original = deepcopy(state); pending = state['items_pending']; boundary = _boundary()
    if (pending is None or pending['status'] != 'pending' or len(state['history']) != pending['index'] + 1
            or not state['identity']['verified'] or not state['identity_evidence'] or state['pending_calls']
            or any(state[k + '_pending'] is not None for k in ('address', 'payment', 'cancellation'))
            or state['handoff']['status'] not in {'not_requested', 'rejected'}):
        raise ValueError('An original idle verified item dispatch is required')
    if pending['mode'] == 'prepare':
        boundary.event(state, 'items_result', {'call_id': pending['call_id']})
        try: decision, state = _prepare(state, api)
        except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
            state = deepcopy(original); boundary.event(state, 'items_result', {'call_id': pending['call_id']})
            decision, state = boundary.reply(state, 'items_preparation_failed', 'Item preparation could not complete; no business write was sent. Clarify or retry preparation.')
    else:
        attempted = {o['version'] for o in state['operations'] if o['mutates']}
        selected = [p for p in _current_records(state) if p['status'] == 'confirmed' and p['version'] not in attempted]
        if len(selected) != 1 or selected[0]['spec']['action'] != 'modify_items':
            raise ValueError('One confirmed complete item proposal is required')
        proposal = selected[0]
        try: runtime = ItemsRuntime(api, claims=claims)
        except (TypeError, ValueError, RuntimeError):
            boundary.event(state, 'items_result', {'call_id': pending['call_id']})
            decision, state = boundary.reply(state, 'items_runtime_unavailable', 'Trusted item runtime is unavailable; no write was sent.')
            return _payload(decision, state, original, pending)
        uncertain = False
        try: result, state = execute_operation(state, proposal['version'], proposal['spec'], runtime)
        except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
            uncertain = True; result = {'code': 'items_operation_uncertain'}
        boundary.event(state, 'items_unknown' if uncertain else 'items_result', {'call_id': pending['call_id']})
        if result['code'] in {'facts_changed', 'facts_unavailable', 'item_selection_changed'}:
            try: decision, state = _prepare(state, api, 'Facts or selected candidates changed; no old-version submission was sent. Review this fresh complete list.')
            except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
                decision, state = boundary.reply(state, 'items_repreparation_failed', 'A fresh item recap could not be prepared; no further write was sent.')
        else:
            text = ('The complete item change is accepted and independently verified. Order is pending (items modified) and locked; payment records do not prove refund arrival.' if result['code'] == 'write_verified'
                    else 'The complete item change is not verified (' + result['code'] + '). I will not repeat an uncertain operation or claim completion.')
            decision, state = boundary.reply(state, 'items_execution_uncertain' if uncertain else result['code'], text,
                decision_kind='allow' if result['code'] == 'write_verified' else 'needs_information',
                records=[{'action': 'modify_items', 'target': proposal['spec']['target'], 'version': proposal['version'],
                          'decision': 'allow' if result['code'] == 'write_verified' else 'needs_information', 'code': result['code']}])
    return _payload(decision, state, original, pending)


def _payload(decision, state, original, pending):
    payload = {'reply': decision.text, 'state': clone_state(state), 'assessment': state['history'][-1]['items_assessment']}
    if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES: return payload
    if pending['mode'] == 'prepare':
        state = deepcopy(original); _boundary().event(state, 'items_result', {'call_id': pending['call_id']})
        decision, state = _boundary().reply(state, 'items_result_budget_exceeded', 'The read-only item result exceeds its budget; original evidence preserved, no write sent.')
        payload = {'reply': decision.text, 'state': clone_state(state), 'assessment': state['history'][-1]['items_assessment']}
        if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES: return payload
    raise WorkflowResultTooLarge('Item outcome exceeds transport budget; never reinterpret as definite rejection')
