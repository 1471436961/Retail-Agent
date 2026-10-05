"""Finite actual-user item-list intake; derived criteria keep their source text.

No assistant/tool narrative contributes an item, condition or payment choice.
Ambiguous language requests clarification rather than weakening a constraint.
"""
import json
import re
from copy import deepcopy

from support_agent.domain.addresses import order_ids
from support_agent.domain.rules import input_error, need, allow


def starts_items_request(text):
    intent = text.split('{', 1)[0]
    return bool(re.search(r'\b(change|modify|replace|swap)\b|修改|更换|换成', intent, re.I)
                and re.search(r'\bitems?\b|商品|规格', intent, re.I))


def request_from_history(history):
    request = None
    for index, entry in enumerate(history):
        if entry['role'] != 'user':
            continue
        text = entry['content'].strip()
        initial = starts_items_request(text)
        structured = re.search(r'(?:items|商品)\s*[:：]\s*(\{.*)', text, re.I | re.S)
        line_start = bool(re.search(r'(?:\bitem\s+|商品\s*)[\w-]+\s*[:：]', text, re.I))
        method = re.search(r'(?:pay\s+with|payment_method_id\s*[:=]|结算方式\s*[:：]|使用支付方式)\s*([\w-]+)', text, re.I)
        removal = re.fullmatch(r'(?:remove|drop|移除|不要修改)\s+(?:item\s+|商品\s*)?([\w-]+)[.!。！]?', text, re.I)
        if not initial and (request is None or not (structured or line_start or method or removal)):
            continue
        if initial:
            ids = order_ids(text.split('{', 1)[0])
            if request is None or ids and ids != [request['order_id']]:
                request = {'order_id': ids[0] if len(ids) == 1 else None, 'lines': [],
                           'method': None, 'request_index': index, 'error': None}
            if len(ids) > 1:
                request['error'] = 'single_order_required'
        request = deepcopy(request)
        request['request_index'] = index
        # A payment-only reply cannot silently repair a rejected/incomplete list.
        if initial or structured or line_start or removal:
            request['error'] = None if request['order_id'] else 'target_order_required'
        if re.search(r'\b(cancel|return|exchange|address|quantity)\b|取消订单|退货|换货|地址|数量', text.split('{', 1)[0], re.I):
            request['error'] = 'mixed_or_quantity_request'
        if structured:
            try:
                body = json.loads(structured[1])
                if (not isinstance(body, dict) or set(body) - {'replacements', 'payment_method_id'}
                        or 'replacements' not in body or not isinstance(body['replacements'], list)):
                    raise ValueError()
                lines = []
                for value in body['replacements']:
                    if isinstance(value, dict) and 'quantity' in value:
                        request['error'] = 'quantity_change_unsupported'
                        raise ValueError()
                    if (not isinstance(value, dict) or not isinstance(value.get('item_id'), str)
                            or set(value) not in ({'item_id', 'criteria'}, {'item_id', 'options'}, {'item_id', 'replacement_item_id'})):
                        raise ValueError()
                    lines.append({**value, 'text': text, 'index': index})
                if 'payment_method_id' in body and (not isinstance(body['payment_method_id'], str) or not body['payment_method_id'].strip()):
                    raise ValueError()
                request['lines'] = lines  # Explicit envelope replaces the whole draft, preserving occurrences.
                request['method'] = {'query': body['payment_method_id'], 'index': index} if 'payment_method_id' in body else None
            except (TypeError, ValueError):
                request['error'] = request['error'] if request['error'] == 'quantity_change_unsupported' else 'invalid_items_json'
        else:
            current = None
            if removal:
                matches = [n for n, line in enumerate(request['lines']) if line['item_id'] == removal[1]]
                if len(matches) != 1:
                    request['error'] = 'ambiguous_item_removal'
                else:
                    request['lines'].pop(matches[0])
            for segment in re.split(r'[;；]', text):
                match = re.search(r'(?:\bitem\s+|商品\s*)([\w-]+)\s*[:：]\s*(.+)', segment, re.I)
                if match:
                    line = {'item_id': match[1], 'text': match[2].strip(), 'index': index}
                    existing = [n for n, old in enumerate(request['lines']) if old['item_id'] == line['item_id']]
                    if re.match(r'\s*(?:add|also|再加|另外)', segment, re.I):
                        request['lines'].append(line)
                    elif len(existing) == 1:
                        request['lines'][existing[0]] = line
                    elif existing:
                        request['error'] = 'ambiguous_item_correction'
                    else:
                        request['lines'].append(line)
                    current = line
                elif current is not None and not re.search(r'pay\s+with|payment_method_id|结算方式', segment, re.I):
                    current['text'] += '; ' + segment.strip()
            if method:
                choices = re.findall(r'(?:pay\s+with|payment_method_id\s*[:=]|结算方式\s*[:：]|使用支付方式)\s*([\w-]+)', text, re.I)
                clause_tail = text[method.end():].split(';', 1)[0].split('；', 1)[0].strip().strip('.!。！')
                if len(set(choices)) != 1 or clause_tail:
                    request['error'] = 'settlement_choice_unresolved'
                else:
                    request['method'] = {'query': method[1], 'index': index}
                    if request['error'] == 'settlement_choice_unresolved':
                        request['error'] = None
    return request


def _blank():
    return {'hard': [], 'change': [], 'relax': [], 'preferences': [], 'fallbacks': [], 'ranking': []}


def criteria_for_line(line, original):
    """Normalize supported phrases using known original option names only."""
    if 'criteria' in line:
        return allow('explicit_criteria', 'Explicit customer criteria retained.', 'U4', details={'criteria': line['criteria']})
    if 'replacement_item_id' in line:
        return allow('explicit_variant', 'Exact variant choice retained for validation.', 'IT-01', details={'variant': line['replacement_item_id']})
    result = _blank()
    if 'options' in line:
        if not isinstance(line['options'], dict) or any(k not in original['options'] or not isinstance(v, str) or not v.strip() for k, v in line['options'].items()):
            return input_error('invalid_item_options', 'Use known option names and string values.', 'IT-01')
        result['hard'] = [{'field': k, 'op': 'eq', 'value': v} for k, v in line['options'].items()]
        result['change'] = list(line['options'])
        return allow('normalized_item_options', 'Requested exact options retained.', 'IT-01', details={'criteria': result})
    variant = re.fullmatch(r'(?:variant|规格)\s+([\w-]+)[.!。！]?', line['text'], re.I)
    if variant:
        return allow('explicit_variant', 'Exact variant choice retained for validation.', 'IT-01', details={'variant': variant[1]})
    if re.search(r'\b(if|unless|after|before)\b|如果|除非|之后|之前', line['text'], re.I):
        return need('item_condition_unresolved', 'Clarify conditional item requirements before candidate selection or confirmation.', 'U4')
    # Fallback branches are parsed separately and remain explicit user choices.
    parts = re.split(r'\s*(?:\botherwise\b|否则)\s*', line['text'], flags=re.I)
    if len(parts) > 2:
        return need('item_condition_unresolved', 'Clarify one primary and one explicit fallback branch.', 'U4')
    branches = []
    aliases = {'颜色': 'color', '尺寸': 'size', '容量': 'capacity', '防水': 'waterproof', '分辨率': 'resolution', '材质': 'material'}
    for phrase in parts:
        branch = _blank()
        tokens = re.split(r'\s*(?:[,，;；]|\band\b|并且)\s*', phrase, flags=re.I)
        for token in tokens:
            token = token.strip().rstrip('.!。！')
            if not token:
                continue
            if re.fullmatch(r'(?:cheapest|lowest price|最便宜|最低价格)', token, re.I):
                branch['ranking'].append({'field': 'price', 'direction': 'min'}); continue
            if re.fullmatch(r'(?:price\s*(?:<=|at most)\s*original|no more than original price|不超过原价)', token, re.I):
                branch['hard'].append({'field': 'price', 'op': 'lte', 'value': {'original': 'price'}}); continue
            price = re.fullmatch(r'(?:price|价格)\s*(<=|>=|<|>)\s*([0-9]+(?:\.[0-9]+)?)', token, re.I)
            if price:
                branch['hard'].append({'field': 'price', 'op': {'<=': 'lte', '>=': 'gte', '<': 'lt', '>': 'gt'}[price[1]], 'value': float(price[2])}); continue
            rank = re.fullmatch(r'(?:highest|largest|maximum|最低|最高|最大)\s+([\w-]+)', token, re.I)
            if rank:
                name = aliases.get(rank[1], rank[1])
                if name not in original['options']:
                    return need('unknown_item_attribute', 'Clarify an attribute present in this item.', 'IT-01')
                branch['change'].append(name)
                branch['ranking'].append({'field': name, 'direction': 'min' if token.startswith('最低') else 'max'}); continue
            relax = re.fullmatch(r'(?:any|relax|任意|不限)\s+([\w-]+)', token, re.I)
            preference = re.fullmatch(r'(?:prefer|偏好)\s+([\w-]+)\s*[:=]\s*(.+)', token, re.I)
            match = re.fullmatch(r'([\w-]+)\s*(?:to\s+|为\s*|[:=]\s*|\s+)(.+)', token, re.I)
            name = aliases.get((relax or preference or match)[1], (relax or preference or match)[1]) if relax or preference or match else None
            if name not in original['options']:
                return need('item_condition_unresolved', 'Clarify exact option names/values, a numeric cap, ranking, or explicit fallback; no unsupported phrase is ignored.', 'U4')
            if relax:
                branch['relax'].append(name)
            elif preference:
                tiers = [[v.strip()] for v in re.split(r'\s*(?:>|\bthen\b|然后)\s*', preference[2])]
                branch['change'].append(name); branch['preferences'].append({'field': name, 'tiers': tiers})
            else:
                branch['change'].append(name); branch['hard'].append({'field': name, 'op': 'eq', 'value': match[2].strip()})
        branch['change'] = list(dict.fromkeys(branch['change']))
        branch['relax'] = list(dict.fromkeys(branch['relax']))
        branches.append(branch)
    if len(branches) == 2 and (branches[1]['preferences'] or branches[1]['ranking']):
        return need('fallback_priority_clarification', 'Use one shared preference/ranking policy and explicit fallback hard/change/relax conditions.', 'U4')
    result = branches[0]
    result['fallbacks'] = [{k: branches[1][k] for k in ('hard', 'change', 'relax')}] if len(branches) == 2 else []
    return allow('item_conditions_normalized', 'Finite customer conditions normalized with their original source retained.', 'U4', details={'criteria': result})
