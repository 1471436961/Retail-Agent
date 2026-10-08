"""Model interpretations of original user language, never backend authority.

The original user content is immutable. The host attaches a separately named
interpretation, with exact user-source quotes and a source-content hash. Replay
checks that binding and the closed candidate schema; it does not claim to prove
the model's semantic judgment or the authenticity of an externally supplied
conversation. Ownership, policy, quotes and execution remain host decisions.
"""
import hashlib
import json
from copy import deepcopy

from support_agent.protocol import InvalidAction

ACTIONS = frozenset({'read', 'summary', 'analysis', 'items', 'exchange', 'returns', 'address', 'payment',
                     'cancellation', 'handoff', 'consent', 'clarify', 'respond'})
BUSINESS = frozenset({'items', 'exchange', 'returns', 'address', 'payment', 'cancellation'})
ARGUMENT_KEYS = {
    'read': {'name', 'arguments'},
    'summary': {'order_ids'},
    'analysis': {'order_id', 'item_ids', 'replacements'},
    'items': {'order_id', 'replacements', 'payment_method_id', 'max_total_price'},
    'exchange': {'order_id', 'replacements', 'payment_method_id', 'max_total_price'},
    'returns': {'order_id', 'item_ids', 'all_items', 'destination'},
    'address': {'order_ids', 'default', 'all_orders', 'source', 'fields', 'full'},
    'payment': {'order_id', 'selection'},
    'cancellation': {'order_id', 'reason', 'scope', 'conditional', 'original_refunds'},
    'consent': {'assignments'}, 'handoff': set(), 'clarify': set(), 'respond': set(),
}


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 4096


def validate_candidate(candidate, history, user_index, *, allow_consent=True):
    """Validate shape and actual-user provenance, not natural-language meaning."""
    if (not isinstance(candidate, dict)
            or set(candidate) != {'action', 'identity', 'arguments', 'sources', 'message'}
            or candidate.get('action') not in ACTIONS):
        raise InvalidAction('Invalid semantic candidate shape')
    if (type(user_index) is not int or not 0 <= user_index < len(history)
            or history[user_index].get('role') != 'user'):
        raise InvalidAction('Semantic candidate requires a real user source')
    identity, args, sources = candidate['identity'], candidate['arguments'], candidate['sources']
    if (not isinstance(identity, dict) or set(identity) - {'email', 'first_name', 'last_name', 'postal_code'}
            or any(not _text(v) for v in identity.values())
            or not isinstance(args, dict) or set(args) - ARGUMENT_KEYS[candidate['action']]
            or not isinstance(sources, list) or len(sources) > 32
            or not isinstance(candidate['message'], str) or len(candidate['message']) > 4096):
        raise InvalidAction('Invalid semantic fields')
    if candidate['action'] not in {'clarify', 'respond'} and not sources:
        raise InvalidAction('Action interpretation requires actual-user quotes')
    quoted = []
    for source in sources:
        if (not isinstance(source, dict) or set(source) != {'index', 'quote'}
                or type(source['index']) is not int or not 0 <= source['index'] <= user_index
                or history[source['index']].get('role') != 'user' or not _text(source['quote'])
                or source['quote'] not in history[source['index']]['content']):
            raise InvalidAction('Semantic source is not an exact real-user quote')
        quoted.append(source['quote'])
    # Names/email/postal proof must actually have been supplied by the user.
    # This is a provenance check; the backend still independently matches them.
    normalized_quotes = ' '.join(' '.join(t.split()).casefold() for t in quoted)
    if any(' '.join(v.split()).casefold() not in normalized_quotes for v in identity.values()):
        raise InvalidAction('Identity interpretation invents user inputs')
    action = candidate['action']
    if action in {'consent', 'handoff'} and (
            not allow_consent or not sources or any(s['index'] != user_index for s in sources)
            or not any(s['quote'] == history[user_index]['content'] for s in sources)):
        raise InvalidAction('Consent and transfer permission require the complete newest user turn')
    if action in BUSINESS and not args:
        raise InvalidAction('Business request has no parameters')
    if action in {'items', 'exchange'}:
        if (not _text(args.get('order_id')) or not isinstance(args.get('replacements'), list)
                or not args['replacements'] or len(args['replacements']) > 128):
            raise InvalidAction('Invalid replacement request')
        for line in args['replacements']:
            if (not isinstance(line, dict) or set(line) not in
                    ({'item_id', 'criteria'}, {'item_id', 'options'}, {'item_id', 'replacement_item_id'})
                    or not _text(line['item_id'])):
                raise InvalidAction('Invalid replacement line')
        if 'payment_method_id' in args and not _text(args['payment_method_id']):
            raise InvalidAction('Invalid settlement choice')
    elif action == 'returns':
        if (set(args) != ARGUMENT_KEYS[action] or not _text(args['order_id'])
                or not isinstance(args['item_ids'], list) or any(not _text(v) for v in args['item_ids'])
                or type(args['all_items']) is not bool
                or (args['all_items'] and args['item_ids'])
                or not isinstance(args['destination'], (dict, type(None)))):
            raise InvalidAction('Invalid return request')
        dest = args['destination']
        if dest is not None and not (dest == {'kind': 'original'} or
                set(dest) == {'kind', 'query', 'exact'} and dest['kind'] == 'saved'
                and _text(dest['query']) and type(dest['exact']) is bool):
            raise InvalidAction('Invalid return destination')
    elif action == 'payment':
        selection = args.get('selection')
        if (set(args) != ARGUMENT_KEYS[action] or not _text(args['order_id'])
                or not isinstance(selection, dict) or set(selection) != {'query', 'fallback', 'exact'}
                or not _text(selection['query']) or type(selection['exact']) is not bool
                or selection['fallback'] is not None and not _text(selection['fallback'])):
            raise InvalidAction('Invalid payment selection')
    elif action == 'cancellation':
        if (set(args) != ARGUMENT_KEYS[action] or not _text(args['order_id'])
                or args['reason'] is not None and not _text(args['reason'])
                or args['scope'] not in {'whole_order', 'partial'}
                or type(args['conditional']) is not bool or type(args['original_refunds']) is not bool):
            raise InvalidAction('Invalid cancellation request')
    elif action == 'address':
        if (set(args) != ARGUMENT_KEYS[action] or not isinstance(args['order_ids'], list)
                or any(not _text(v) for v in args['order_ids'])
                or any(type(args[k]) is not bool for k in ('default', 'all_orders', 'full'))
                or not isinstance(args['fields'], dict) or not isinstance(args['source'], dict)):
            raise InvalidAction('Invalid address request')
        from support_agent.domain.addresses import FIELDS
        if (set(args['fields']) - set(FIELDS) or any(not isinstance(v, str) and
                not (k == 'address_line_2' and v is None) for k, v in args['fields'].items())):
            raise InvalidAction('Invalid address fields')
        source = args['source']
        if not (source in ({'kind': 'record'}, {'kind': 'default'}, {'kind': 'original_default'})
                or set(source) == {'kind', 'order_id'} and source['kind'] == 'order' and _text(source['order_id'])):
            raise InvalidAction('Invalid address source')
    elif action == 'read':
        from support_agent.protocol import READ_TOOL_FIELDS
        if (set(args) != ARGUMENT_KEYS[action] or args['name'] not in READ_TOOL_FIELDS
                or not isinstance(args['arguments'], dict)):
            raise InvalidAction('Invalid semantic read action')
    elif action == 'summary':
        if (set(args) != {'order_ids'} or not isinstance(args['order_ids'], list) or not args['order_ids']
                or any(not _text(v) for v in args['order_ids']) or len(set(args['order_ids'])) != len(args['order_ids'])):
            raise InvalidAction('Invalid amount summary scope')
    elif action == 'analysis':
        if (set(args) != ARGUMENT_KEYS[action] or not _text(args['order_id'])
                or not isinstance(args['item_ids'], list) or not args['item_ids']
                or any(not _text(v) for v in args['item_ids'])
                or not isinstance(args['replacements'], list)):
            raise InvalidAction('Invalid read-only analysis scope')
        for row in args['replacements']:
            if (not isinstance(row, dict) or set(row) not in
                    ({'item_id', 'criteria'}, {'item_id', 'options'}, {'item_id', 'replacement_item_id'})
                    or not _text(row['item_id'])):
                raise InvalidAction('Invalid analysis replacement')
    elif action == 'consent':
        if not allow_consent or set(args) != {'assignments'} or not isinstance(args['assignments'], list) or not args['assignments']:
            raise InvalidAction('Consent requires a new user turn')
        seen = set()
        for row in args['assignments']:
            if (not isinstance(row, dict) or set(row) != {'version', 'decision'}
                    or type(row['version']) is not int or row['version'] <= 0 or row['version'] in seen
                    or row['decision'] not in {'confirm', 'withdraw', 'amend', 'condition', 'defer'}):
                raise InvalidAction('Invalid scoped consent interpretation')
            seen.add(row['version'])
        if not sources or any(s['index'] != user_index for s in sources):
            raise InvalidAction('Consent cannot be inherited from earlier user turns')
        if not any(s['quote'] == history[user_index]['content'] for s in sources):
            raise InvalidAction('Consent must preserve the complete latest reply, including conditions')
    json.dumps(candidate, allow_nan=False)  # No NaN or non-JSON candidates.
    return deepcopy(candidate)


def annotate(history, user_index, candidate, *, allow_consent=True):
    candidate = validate_candidate(candidate, history, user_index, allow_consent=allow_consent)
    history[user_index]['interpretation'] = {'source_sha256': digest(history[user_index]['content']),
                                           'candidate': candidate}


def frame(entry):
    return entry.get('interpretation', {}).get('candidate') if entry.get('role') == 'user' else None


def validate_history(history):
    for index, entry in enumerate(history):
        if 'interpretation' not in entry:
            continue
        data = entry['interpretation']
        if (entry.get('role') != 'user' or not isinstance(data, dict)
                or set(data) != {'source_sha256', 'candidate'} or data['source_sha256'] != digest(entry['content'])):
            raise InvalidAction('Invalid interpretation provenance')
        validate_candidate(data['candidate'], history, index)


def identity_fields(entry):
    candidate = frame(entry)
    if candidate is not None:
        return deepcopy(candidate['identity'])
    from support_agent.domain.identity import fields_from_text
    return fields_from_text(entry['content'])


def request(entry, index, kind):
    """Translate typed intent to existing planning inputs; never user text."""
    candidate = frame(entry)
    if candidate is None or candidate['action'] != kind:
        return None
    args = deepcopy(candidate['arguments'])
    if kind in {'items', 'exchange'}:
        result = {'order_id': args['order_id'], 'lines': [dict(v, text=entry['content'], index=index)
                  for v in args['replacements']], 'method': {'query': args['payment_method_id'], 'index': index}
                  if 'payment_method_id' in args else None, 'request_index': index, 'error': None}
        if 'max_total_price' in args:
            result['max_total_price'] = args['max_total_price']
        return result
    if kind == 'returns':
        opening = min((s['index'] for s in candidate['sources']), default=index)
        return dict(args, request_index=index, opening_request_index=opening, list_index=index,
                    destination_index=index if args['destination'] else None, error=None)
    if kind == 'cancellation':
        error = ('cancellation_whole_order_required' if args['scope'] == 'partial' else
                 'conditional_cancellation_request' if args['conditional'] else
                 'cancellation_original_destination_required' if not args['original_refunds'] else None)
        return {'order_id': args['order_id'], 'reason': args['reason'], 'request_index': index, 'error': error}
    return dict(args, request_index=index, error=None)


def active_action(state):
    entry = next((e for e in reversed(state['history']) if e['role'] == 'user'), {})
    candidate = frame(entry)
    return candidate['action'] if candidate else None


def consent_assignments(entry, records):
    candidate = frame(entry)
    if candidate is None:
        return None
    if candidate['action'] != 'consent':
        return 'unresolved', [('unresolved', list(range(len(records))))]
    versions = {p['version']: i for i, p in enumerate(records)}
    rows = candidate['arguments']['assignments']
    if any(row['version'] not in versions for row in rows):
        return 'unresolved', [('unresolved', list(range(len(records))))]
    mapping = {'defer': 'unresolved'}
    assignments = [(mapping.get(row['decision'], row['decision']), [versions[row['version']]]) for row in rows]
    decisions = {row['decision'] for row in rows}
    kind = next(iter(decisions)) if len(decisions) == 1 and len(rows) == len(records) else 'partial'
    return ('unresolved' if kind == 'defer' else kind), assignments
