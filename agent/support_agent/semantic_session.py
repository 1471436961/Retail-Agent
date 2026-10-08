"""Orchestrate model understanding through deterministic read/plan/consent gates."""
from support_agent.protocol import InvalidAction
from support_agent.workflow_registry import WORKFLOW_KINDS

MAX_SEMANTIC_CALLS_PER_REQUEST = 8  # Internal model/read planning loop, not retries.


def enabled(adapter):
    return (adapter is not None and getattr(adapter, 'semantic_understanding', False) is True
            and callable(getattr(adapter, 'understand', None)))


def interpret(state, adapter, *, user_text=None):
    if any(state[k + '_pending'] is not None for k in WORKFLOW_KINDS):
        raise InvalidAction('Unresolved workflow blocks semantic delegation')
    if state['model_calls_since_user'] >= MAX_SEMANTIC_CALLS_PER_REQUEST:
        raise InvalidAction('Semantic planning budget exhausted')
    state['model_calls_since_user'] += 1
    try:
        return adapter.understand(state, user_text=user_text)
    finally:
        usage = getattr(adapter, 'last_usage', None)
        if usage is not None:
            state['model_usage'].append({'turn': state['turn'], **usage})


def route(state, candidate, *, proposal_reply=None):
    from support_agent.read_session import reply, emit
    from support_agent.proposals import _current_records
    action, args = candidate['action'], candidate['arguments']
    if action == 'handoff':
        from support_agent.handoff_session import route_handoff
        return route_handoff(state, state['user_request'])
    if action in {'clarify', 'respond'}:
        return reply(state, candidate['message'] or 'Please clarify what you would like me to do.')
    if not state['identity']['verified'] or not state['identity_evidence']:
        return reply(state, candidate['message'] or 'Please provide your email, or your first and last name and postal code, so I can verify your account.')
    if action == 'read':
        return emit(state, args['name'], args['arguments'])
    if action == 'summary':
        from support_agent.amount_summary import route_summary
        return route_summary(state, order_ids=args['order_ids'])
    if action == 'analysis':
        from support_agent.read_session import route_scope_analysis
        return route_scope_analysis(state, arguments=args)
    from support_agent.items_session import route_items
    from support_agent.exchange_session import route_exchange
    from support_agent.returns_session import route_returns
    from support_agent.address_session import route_address
    from support_agent.payment_session import route_payment
    from support_agent.cancellation_session import route_cancellation
    routes = {'items': route_items, 'exchange': route_exchange, 'returns': route_returns,
              'address': route_address, 'payment': route_payment, 'cancellation': route_cancellation}
    if action == 'consent':
        attempted = {o['version'] for o in state['operations'] if o['mutates']}
        records = [p for p in _current_records(state) if p['status'] == 'confirmed' and p['version'] not in attempted]
        kinds = {'modify_items': 'items', 'exchange': 'exchange', 'return': 'returns',
                 'shipping_address': 'address', 'default_shipping_address': 'address',
                 'payment_method': 'payment', 'cancel': 'cancellation'}
        selected = {kinds[p['spec']['action']] for p in records}
        if len(selected) == 1:
            # Existing producers re-check exact version, freshness, source,
            # confirmed scope, private facts and claim before any send.
            result = routes[next(iter(selected))](state, text='')
            if result is not None:
                return result
        return reply(state, proposal_reply['text'] if proposal_reply and proposal_reply.get('text') else
                     'The selected proposals need review; no additional business operation was sent.')
    if action in routes:
        result = routes[action](state)
        if result is not None:
            return result
    raise InvalidAction('No deterministic planner accepted this candidate')


def after_read(state, adapter):
    from support_agent.semantics import annotate, frame
    current = next(e for e in reversed(state['history']) if e['role'] == 'user')
    old = frame(current)
    if old and old['action'] == 'analysis' and state['identity']['verified']:
        from support_agent.read_session import route_scope_analysis
        return route_scope_analysis(state, arguments=old['arguments'])
    if old and old['action'] == 'summary' and state['identity']['verified']:
        from support_agent.amount_summary import route_summary
        refreshed = state['operations'][-1]['name'] in {'list_customer_orders', 'get_order'}
        return route_summary(state, order_ids=old['arguments']['order_ids'], after_reads=refreshed)
    candidate = interpret(state, adapter)
    index = max(i for i, e in enumerate(state['history']) if e['role'] == 'user')
    annotate(state['history'], index, candidate, allow_consent=False)
    return route(state, candidate)
