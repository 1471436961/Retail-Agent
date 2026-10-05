"""Finite actual-user return list/destination intake; no API or consent."""
import json
import re
from copy import deepcopy
from support_agent.domain.rules import identifier


def starts_returns_request(text):
    return bool(re.match(r'^(?:please\s+)?(?:return\b|start (?:a )?return\b|退货|退回)', text.strip(), re.I))


def _selection(text):
    text = text.strip().rstrip('.!。！')
    if re.fullmatch(r'original(?: payment(?: method)?)?|原(?:支付方式|路)', text, re.I):
        return {'kind': 'original'}
    if not text or re.search(r'\b(?:if|unless|otherwise|and|or)\b|如果|否则|或者|以及', text, re.I):
        raise ValueError('refund_destination_unresolved')
    return {'kind': 'saved', 'query': text, 'exact': bool(re.fullmatch(r'[\w-]+', text) and '_' in text)}


def _ids(text):
    text = text.strip().rstrip('.!。！')
    if re.fullmatch(r'all(?: items)?|全部(?:商品)?', text, re.I):
        return None, True
    if text.startswith('['):
        values = json.loads(text)
    else:
        values = [v.strip() for v in re.split(r',|、|，', text)]
        if any(not re.fullmatch(r'[\w-]+', v) for v in values):
            raise ValueError('invalid_return_list')
    if not isinstance(values, list) or not values or any(not identifier(v) for v in values):
        raise ValueError('invalid_return_list')
    return values, False


def request_from_history(history):
    request = None
    openings = {}
    for index, entry in enumerate(history):
        if entry.get('role') != 'user':
            continue
        text = entry['content'].strip()
        starts = starts_returns_request(text)
        if not starts and request is None:
            continue
        if not starts and not re.match(r'^(?:items?\b|item_ids\b|only items?\b|add item\b|remove item\b|refund\b|refund_payment_method_id\b|商品|仅退|追加商品|移除商品|退款)', text, re.I):
            continue
        previous = request
        if starts:
            orders = re.findall(r'#[A-Za-z0-9_-]+', text.split('{', 1)[0])
            order = orders[0] if len(orders) == 1 else None
            if order is not None:
                openings.setdefault(order, index)
            request = deepcopy(previous) if previous and previous['order_id'] == order else {
                'order_id': order, 'item_ids': [], 'all_items': False, 'destination': None,
                'opening_request_index': openings.get(order, index), 'list_index': None, 'destination_index': None}
        else:
            request = deepcopy(request)
        request.update(request_index=index, error=None)
        try:
            if starts and request['order_id'] is None:
                raise ValueError('return_order_required')
            if '{' in text:
                header, raw = text.split('{', 1)
                if not re.fullmatch(r'(?:.*?\bitems\s*[:：]?\s*|.*?商品\s*[:：]?\s*)', header, re.I):
                    raise ValueError('invalid_return_json')
                body = json.loads('{' + raw)
                if not isinstance(body, dict) or set(body) - {'item_ids', 'refund_payment_method_id'} or 'item_ids' not in body:
                    raise ValueError('invalid_return_json')
                ids = body['item_ids']
                if not isinstance(ids, list) or not ids or any(not identifier(v) for v in ids):
                    raise ValueError('invalid_return_list')
                request.update(item_ids=ids, all_items=False, list_index=index, destination=None, destination_index=None)
                if 'refund_payment_method_id' in body:
                    if not identifier(body['refund_payment_method_id']):
                        raise ValueError('invalid_refund_method_id')
                    request.update(destination={'kind': 'saved', 'query': body['refund_payment_method_id'], 'exact': True}, destination_index=index)
                continue
            # Only natural-language control clauses can describe other actions;
            # JSON instrument/item strings above remain data.
            if re.search(r'\bcancel\b|\bexchange\b|\b(?:change|modify)\b|取消订单|换货|改地址|更换支付', text, re.I):
                raise ValueError('mixed_return_request')
            parts = re.split(r';|；', text)
            if starts:
                parts[0] = re.sub(r'^(?:please\s+)?(?:return(?:\s+order)?|start (?:a )?return(?:\s+order)?|退货(?:订单)?|退回(?:订单)?)\s*#[A-Za-z0-9_-]+\s*', '', parts[0], flags=re.I)
            list_changed = destination_changed = False
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                match = re.fullmatch(r'(?:refund_payment_method_id|refund(?:\s+to)?|退款(?:至|到)?)\s*[:：=]?\s*(.+)', part, re.I)
                if match:
                    request.update(destination=_selection(match[1]), destination_index=index)
                    destination_changed = True
                    continue
                match = re.fullmatch(r'(?:add item|追加商品)\s+([\w-]+)', part, re.I)
                if match:
                    if request['all_items'] or not request['item_ids']:
                        raise ValueError('return_list_required_before_add')
                    request['item_ids'].append(match[1]); request['list_index'] = index; list_changed = True
                    continue
                match = re.fullmatch(r'(?:remove item|移除商品)\s+([\w-]+)', part, re.I)
                if match:
                    if request['all_items'] or request['item_ids'].count(match[1]) != 1:
                        raise ValueError('return_remove_ambiguous')
                    request['item_ids'].remove(match[1]); request['list_index'] = index; list_changed = True
                    continue
                match = re.fullmatch(r'(?:only\s+)?(?:item_ids|items?|商品|仅退)\s*[:：=]?\s*(.+)', part, re.I)
                if match:
                    ids, all_items = _ids(match[1])
                    request.update(item_ids=ids, all_items=all_items, list_index=index); list_changed = True
                    continue
                raise ValueError('return_request_unresolved')
            if (previous and previous.get('error') and not list_changed and destination_changed
                    and previous['error'] not in {'refund_destination_unresolved', 'invalid_refund_method_id'}):
                request['error'] = previous['error']
        except (TypeError, ValueError, KeyError) as exc:
            code = str(exc)
            request['error'] = code if code.startswith(('return_', 'invalid_', 'mixed_', 'refund_')) else 'invalid_return_json'
    return request
