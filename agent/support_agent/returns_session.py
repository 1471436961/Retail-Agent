"""Default complete delivered-order return producer; no independent refunds."""
import json
import re
from copy import deepcopy
from support_agent.workflow_registry import WORKFLOW_KINDS
from support_agent.address_session import _safe_read
from support_agent.adapters.write_runtime import SessionWriteRuntime
from support_agent.domain.catalog import return_refund_basis
from support_agent.domain.orders import order_state_rule
from support_agent.domain.payment_intake import choose_method, method_label
from support_agent.domain.policies import return_destination_rule, _methods, refund_timing_rule
from support_agent.domain.returns_intake import request_from_history, starts_returns_request
from support_agent.domain.rules import allow, need, input_error, deny
from support_agent.protocol import InvalidAction
from support_agent.proposals import _current_records, _scope_facts, normalize_spec, present_proposals
from support_agent.state import clone_state
from support_agent.tasks import present_task_plan
from support_agent.workflow_boundary import WorkflowBoundary, unfinished_other_tasks
from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES, WorkflowResultTooLarge, json_bytes


def _boundary():
    return WorkflowBoundary('returns', MAX_WORKFLOW_RESULT_BYTES)


def build_plan(history):
    request = request_from_history(history)
    if request is None:
        return need('return_request_required', 'Specify one owned delivered order and the complete item list.', 'RT-01')
    if request['error']:
        kind = input_error if request['error'].startswith('invalid_') else deny if request['error'] == 'mixed_return_request' else need
        return kind(request['error'], 'Clarify the complete return list or one refund destination; no mixed action is submitted.', 'RT-01', 'RT-02')
    # The caller already validated history. This replays accepted facts only,
    # including the fixed opening source; it performs no API requests.
    from support_agent.state import initial_state
    from support_agent.proposals import _clean_read_history
    prefix = initial_state(_clean_read_history(history))
    target = {'customer_id': prefix['identity']['customer_id'], 'order_id': request['order_id']}
    try:
        facts = _scope_facts(history, {'action': 'return', 'target': target}, state_only=True)
    except (TypeError, ValueError, KeyError):
        return need('return_facts_required', 'Read the verified profile and owned order first.', 'U3')
    order, customer = facts['order'], facts['customer']
    guard = order_state_rule(order, 'return')
    if guard['decision'] != 'allow': return guard
    ids = [item['item_id'] for item in order['items']] if request['all_items'] else request['item_ids']
    if not ids:
        return need('complete_return_list_required', 'Which original item IDs, including repeated instances, belong in the one complete return request?', 'RT-01')
    estimate = return_refund_basis(order['items'], ids)
    if estimate['decision'] != 'allow': return estimate
    opening = facts['opening_payment_methods']
    choice = request['destination']
    candidates = return_destination_rule(customer['payment_methods'], order['payments'], None, opening_payment_methods=opening)
    # Enumeration normally requests a choice, even for one candidate. Preserve
    # specific fact errors before parsing the same saved records a second time.
    if candidates['code'] != 'refund_destination_choice_required':
        return candidates
    methods = _methods(customer['payment_methods'])
    if choice is None:
        # A unique legal destination needs no invented alternative or magic
        # word. Multiple legal destinations are a real customer choice.
        available = [i for i in candidates['details'].get('candidate_ids', []) if i in methods]
        if len(available) != 1: return candidates
        selected = available[0]
    elif choice['kind'] == 'original':
        originals = list(dict.fromkeys(row['payment_method_id'] for row in order['payments'] if row['transaction_type'] == 'payment'))
        if len(originals) != 1:
            return need('original_refund_choice_ambiguous', 'Several original instruments exist; select one legal destination explicitly.', 'RT-02', details={'candidate_ids': originals})
        selected = originals[0]
    else:
        result = choose_method(customer['payment_methods'], choice)
        if result['decision'] != 'allow': return result
        selected = result['details']['payment_method_id']
    destination = return_destination_rule(customer['payment_methods'], order['payments'], selected, opening_payment_methods=opening)
    if destination['decision'] != 'allow': return destination
    if selected not in methods:
        return need('return_saved_destination_unavailable', 'The original destination is absent from current saved instruments; choose an eligible existing destination or request human help.', 'RT-02')
    spec = normalize_spec({'action':'return','target':target,
        'parameters':{'item_ids':ids,'refund_payment_method_id':selected},
        'amount':{'kind':'estimated_refund','value':estimate['details']['aggregate_amount'],'estimate_method':estimate['details']['estimate_method']}})
    timing = refund_timing_rule(methods[selected]['source'])
    sources = [{ 'history_index':i, 'user_text':history[i]['content']} for i in dict.fromkeys(
        i for i in (request['opening_request_index'], request['list_index'], request['destination_index']) if i is not None)]
    return allow('complete_return_ready', 'Complete original-unit selection, labelled estimate and legal destination are resolved.', 'RT-01','RT-02',
        details={'request':request,'sources':sources,'spec':spec,'estimate':estimate['details'],
                 'opening_profile_index':facts['opening_profile_index'],'opening_payment_methods':opening,
                 'method_label':method_label(methods[selected]),'timing':timing['details']['timing'] + '; ' + timing['message']})


def validate_returns_basis(state):
    for index, entry in enumerate(state['history']):
        if 'returns_basis' not in entry: continue
        result = build_plan(state['history'][:index])
        if (set(entry) != {'role','content','returns_basis'} or entry['role'] != 'assistant'
                or result['code'] != 'complete_return_ready' or entry['returns_basis'] != result['details']
                or entry['content'] != 'Return intake evidence: ' + json.dumps(result['details'], sort_keys=True)):
            raise ValueError('Return list, destination or frozen opening source differs from actual user and accepted history')


def route_returns(state, text=None):
    if state['returns_pending'] is not None:
        return _boundary().reply(state, 'returns_workflow_unresolved', 'The return outcome remains unresolved; do not repeat the request.')
    request = request_from_history(state['history'])
    if request is None: return None
    if request['order_id'] is None:
        if text is not None and starts_returns_request(text):
            return _boundary().reply(state, 'return_order_required', 'Specify one owned delivered order for the return request.')
        return None
    latest = next((i for i in range(len(state['history'])-1,-1,-1) if state['history'][i]['role']=='user'), None)
    from support_agent.domain.items_intake import request_from_history as items_request
    from support_agent.domain.payment_intake import request_from_history as payment_request
    from support_agent.domain.addresses import request_from_history as address_request
    from support_agent.domain.cancellation_intake import request_from_history as cancellation_request
    if any(other and other['request_index'] > request['request_index'] for other in
           (items_request(state['history']),payment_request(state['history']),address_request(state['history']),cancellation_request(state['history']))):
        return None
    if text is not None and not starts_returns_request(text) and request['request_index'] != latest:
        attempted={o['version'] for o in state['operations'] if o['mutates']}
        selected=[p for p in _current_records(state) if p['spec']['action']=='return' and p['status']=='confirmed' and p['version'] not in attempted]
        produced = any(e.get('returns_basis', {}).get('spec') == selected[0]['spec'] for e in state['history']) if len(selected)==1 else False
        if produced and selected[0]['confirmation']['history_index']==latest:
            return _boundary().dispatch(state,'execute')
        if not re.fullmatch(r'retry|try again|重试|重新准备',text.strip(),re.I): return None
    return _boundary().dispatch(state,'prepare')


def _prepare(state, api, notice=''):
    boundary = _boundary(); request = request_from_history(state['history'])
    if request is None or request['error']:
        result = build_plan(state['history'])
        return boundary.reply(state,result['code'],result['message'],decision_kind=result['decision'])
    if state['tool_calls_since_user'] + 2 > 12:
        return boundary.reply(state,'returns_read_budget_exceeded','Return refresh exceeds the read budget; no return POST was sent.')
    _, status = _safe_read(state,api,'read_customer_profile',{})
    if status != 'succeeded': return boundary.reply(state,'returns_profile_read_failed','Profile refresh failed; do not substitute an old current destination.')
    from support_agent.adapters.read_api import customer_order_ids
    if request['order_id'] not in customer_order_ids(state['customer_record']):
        return boundary.reply(state,'returns_order_not_owned','This order is not in your verified references; no order GET or return POST.',decision_kind='deny')
    _, status = _safe_read(state,api,'get_order',{'order_id':request['order_id']})
    if status != 'succeeded': return boundary.reply(state,'returns_order_read_failed','The owned order read failed; an old delivered status cannot replace it.')
    result = build_plan(state['history'])
    if result['decision'] != 'allow': return boundary.reply(state,result['code'],result['message'],decision_kind=result['decision'],**result['details'])
    if unfinished_other_tasks(state,{'return'},target=result['details']['spec']['target']) or any(p['spec']['action']!='return' and p['version'] not in {o['version'] for o in state['operations'] if o['mutates']} for p in _current_records(state)):
        return boundary.reply(state,'returns_mixed_plan_requires_review','An unfinished different operation requires a final choice; it was not silently discarded.')
    data = result['details']; notes = [notice] if notice else []
    notes.append('Current order status: delivered. Complete return list (each row is one purchased unit):')
    for number, item in enumerate(data['estimate']['items'],1):
        notes.append(f"Unit {number}: {item['item_id']}; {item['name']}; original options {json.dumps(item['options'],ensure_ascii=False)}; original price {item['price']}.")
    notes += [f"Exact selected original-price sum: {data['estimate']['exact_price_sum']}. Estimated refund: {data['estimate']['aggregate_amount']:.2f} (decimal sum, half-up cents; project display rule, not backend settlement).",
              f"Refund destination: {data['method_label']}; channel policy after processing: {data['timing']}",
              'This submits one complete return request per order; after acceptance no items can be added. An accepted application does not prove refund execution, settlement or arrival.']
    note='\n'.join(notes)
    if len(note)>4096:
        return boundary.reply(state,'returns_recap_budget_exceeded','The complete return recap exceeds this entry point; nothing was truncated or submitted. Do not split the request; human assistance is required.')
    state['history'].append({'role':'assistant','content':'Return intake evidence: '+json.dumps(data,sort_keys=True),'returns_basis':deepcopy(data)})
    _,state=present_task_plan(state,[{'action':'return','target':data['spec']['target']}])
    decision,state=present_proposals(state,[data['spec']],presentation_note=note)
    return boundary.tag(decision,state,'returns_confirmation_required',sources=data['sources'])


class ReturnsRuntime(SessionWriteRuntime):
    def assess_business(self,state,spec):
        result=build_plan(state['history'])
        if result['code']!='complete_return_ready': return result
        if result['details']['spec']!=spec:
            return need('return_selection_changed','Fresh return units, estimate or destination changed; prepare a new complete recap.', 'CF-01')
        return super().assess_business(state,spec)


def run_returns_workflow(state,api,claims):
    from support_agent.write_session import execute_operation
    state=clone_state(state); original=deepcopy(state); pending=state['returns_pending']; boundary=_boundary()
    if (pending is None or pending['status']!='pending' or len(state['history'])!=pending['index']+1
            or not state['identity']['verified'] or not state['identity_evidence'] or state['pending_calls']
            or any(state[k+'_pending'] is not None for k in WORKFLOW_KINDS if k != 'returns')
            or state['handoff']['status'] not in {'not_requested','rejected'}):
        raise ValueError('An original idle verified return dispatch is required')
    if pending['mode']=='prepare':
        boundary.event(state,'returns_result',{'call_id':pending['call_id']})
        try: decision,state=_prepare(state,api)
        except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
            state=deepcopy(original); boundary.event(state,'returns_result',{'call_id':pending['call_id']})
            decision,state=boundary.reply(state,'returns_preparation_failed','Return preparation could not complete; no business write was sent. Clarify or retry preparation.')
    else:
        attempted={o['version'] for o in state['operations'] if o['mutates']}
        selected=[p for p in _current_records(state) if p['status']=='confirmed' and p['version'] not in attempted]
        if len(selected)!=1 or selected[0]['spec']['action']!='return': raise ValueError('One confirmed complete return proposal is required')
        proposal=selected[0]
        try: runtime=ReturnsRuntime(api,claims=claims)
        except (TypeError,ValueError,RuntimeError):
            boundary.event(state,'returns_result',{'call_id':pending['call_id']})
            decision,state=boundary.reply(state,'returns_runtime_unavailable','Trusted return runtime is unavailable; no write was sent.')
            return _payload(decision,state,original,pending)
        uncertain=False
        try: result,state=execute_operation(state,proposal['version'],proposal['spec'],runtime)
        except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
            uncertain=True; result={'code':'returns_operation_uncertain'}
        boundary.event(state,'returns_unknown' if uncertain else 'returns_result',{'call_id':pending['call_id']})
        if result['code'] in {'facts_changed','facts_unavailable','return_selection_changed'}:
            try: decision,state=_prepare(state,api,'Fresh facts changed; no old-version request was sent. Review this complete return recap.')
            except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
                decision,state=boundary.reply(state,'returns_repreparation_failed','The new return recap could not complete; no further write was sent.')
        else:
            text=('Your complete return request was accepted and independently verified as return requested. This proves the application only, not refund execution, settlement or arrival; no items can be added.'
                  if result['code']=='write_verified' else 'The return request is not verified ('+result['code']+'). I will not automatically repeat an uncertain request or claim a refund.')
            decision,state=boundary.reply(state,'returns_execution_uncertain' if uncertain else result['code'],text,
                decision_kind='allow' if result['code']=='write_verified' else 'needs_information',
                records=[{'action':'return','target':proposal['spec']['target'],'version':proposal['version'],'decision':'allow' if result['code']=='write_verified' else 'needs_information','code':result['code']}])
    return _payload(decision,state,original,pending)


def _payload(decision,state,original,pending):
    payload={'reply':decision.text,'state':clone_state(state),'assessment':state['history'][-1]['returns_assessment']}
    if json_bytes(payload)<=MAX_WORKFLOW_RESULT_BYTES: return payload
    if pending['mode']=='prepare':
        state=deepcopy(original); _boundary().event(state,'returns_result',{'call_id':pending['call_id']})
        decision,state=_boundary().reply(state,'returns_result_budget_exceeded','Read-only return result exceeds budget; original evidence preserved, no write sent.')
        payload={'reply':decision.text,'state':clone_state(state),'assessment':state['history'][-1]['returns_assessment']}
        if json_bytes(payload)<=MAX_WORKFLOW_RESULT_BYTES: return payload
    raise WorkflowResultTooLarge('Return outcome exceeds budget; never reinterpret as a definite rejection')
