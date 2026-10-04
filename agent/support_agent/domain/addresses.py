"""Bounded bilingual address intake; only actual user text supplies intent.

No geocoder, date ordering, customer-name field or address-book API is inferred.
The workflow asks for clarification outside this grammar rather than guessing.
"""
import json
import re
from copy import deepcopy

FIELDS = ("address_line_1", "address_line_2", "city", "region", "country", "postal_code")
REQUIRED = frozenset(FIELDS) - {"address_line_2"}
ALIASES = {
    "address_line_1": "address_line_1|address line 1|street|街道|地址行1",
    "address_line_2": "address_line_2|address line 2|apartment|suite|unit|公寓|地址行2",
    "city": "city|城市", "region": "region|state|州|省",
    "country": "country|国家", "postal_code": "postal_code|postal code|zip code|zip|邮编",
}
LABEL = re.compile(r"(?<![\w])(" + "|".join(ALIASES.values()) + r")\s*(?:[:：=]|\bto\b|改为|改成)\s*", re.I)


def address_fields(text):
    """Return supplied fields, full-address flag, and explicit input error."""
    structured = re.search(r"(?:address|地址)\s*[:：=]\s*(\{.*\})", text, re.I | re.S)
    if structured:
        try:
            data = json.loads(structured[1])
        except (TypeError, ValueError):
            return {}, True, "invalid_address_json"
        if (not isinstance(data, dict) or set(data) - set(FIELDS)
                or any(not isinstance(v, str) and not (k == "address_line_2" and v is None) for k, v in data.items())):
            return {}, True, "unsupported_address_fields"
        return data, True, None
    fields = {}
    matches = list(LABEL.finditer(text))
    for i, match in enumerate(matches):
        label = match[1].casefold()
        key = next(k for k, aliases in ALIASES.items() if label in aliases.split("|"))
        value = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        value = value.strip(" \t\r\n,;，；.。\"'")
        if key == "address_line_2" and value.casefold() in {"none", "null", "remove", "clear", "无", "删除", "清空"}:
            value = None
        if key in fields and fields[key] != value:
            return {}, False, "ambiguous_address_fields"
        fields[key] = value
    if fields:
        return fields, bool(re.search(r"\bnew address\b|全新地址|新地址", text, re.I)), None
    # Explicit comma-separated complete address, five fields plus optional unit.
    literal = re.search(r"(?:address\s+to|地址改为|地址改成)\s+(.+)$", text, re.I)
    if literal:
        parts = [p.strip(" .。") for p in re.split(r"[,，]", literal[1])]
        if len(parts) in {5, 6}:
            keys = FIELDS if len(parts) == 6 else tuple(k for k in FIELDS if k != "address_line_2")
            return dict(zip(keys, parts)), True, None
        return {}, True, "complete_address_required"
    return {}, False, None


def order_ids(text):
    values = re.findall(r"#[\w-]+", text)
    values += re.findall(r"(?:order[_ ]id|order number|订单号)\s*[:：=]\s*([^\s,;，；]+)", text, re.I)
    return list(dict.fromkeys(values))


def starts_address_request(text):
    return bool(re.search(r"address|地址", text, re.I) and re.search(
        r"\b(change|update|fix|correct|set|use|restore|copy|revert)\b|修改|更改|改为|改成|更新|修正|纠正|设为|改回|恢复|用.*地址|复制", text, re.I))


def request_from_history(history):
    """Fold user intake only. This draft is never a confirmation or a write."""
    request = None
    for index, entry in enumerate(history):
        if entry["role"] != "user":
            continue
        text = entry["content"]
        fields, full, error = address_fields(text)
        if starts_address_request(text):
            # Record selectors come from the request clause, never an address
            # JSON value (a street may itself contain an order-like token).
            intent = text.split("{", 1)[0]
            label = LABEL.search(intent)
            if label:
                intent = intent[:label.start()]
            literal = re.search(r"address\s+to|地址改为|地址改成", intent, re.I)
            if literal:
                intent = intent[:literal.end()]
            if re.search(r"\b(if|unless|after|before|first|then)\b|如果|只要|除非|先.*再|之后|之前", intent, re.I):
                error = error or "conditional_address_request"
            source = {"kind": "record"}
            source_order = re.search(r"(?:from\s+order|从订单)\s*(#[\w-]+)", intent, re.I)
            if source_order:
                source = {"kind": "order", "order_id": source_order[1]}
            elif re.search(r"(?:use|copy).*?(?:my )?default address|用.*默认地址|复制.*默认地址", intent, re.I):
                source = {"kind": "default"}
            elif re.search(r"original default|restore.*default|revert.*default|原.*默认地址|默认地址.*改回", intent, re.I):
                source = {"kind": "original_default"}
            ids = [v for v in order_ids(intent) if v != source.get("order_id")]
            default = bool(re.search(r"\bdefault\b|profile address|account address|默认地址|档案地址", intent, re.I))
            if source["kind"] == "default" and re.search(r"order|订单", intent, re.I):
                default = bool(re.search(r"(?:and|also).*default address|同时.*默认地址", intent, re.I))
            all_orders = bool(re.search(r"all.*(?:pending )?orders|全部.*订单|所有.*订单", intent, re.I))
            if request is not None and fields and not default and not ids and not all_orders and source["kind"] == "record":
                request["fields"].update(fields)
                request.update(request_index=index, full=request["full"] or full,
                               error=error or (request["error"] if request["error"] == "conditional_address_request" else None))
                continue
            if not default and not ids and not all_orders and re.search(r"order|订单", intent, re.I):
                error = error or "target_order_required"
            if not default and not ids and not all_orders:
                error = error or "address_record_required"
            if re.search(r"\b(cancel|exchange|refund|payment|items?)\b|取消订单|换货|退款|支付|商品", intent, re.I):
                error = error or "mixed_business_request"
            request = {"request_index": index, "default": default, "order_ids": ids,
                       "all_orders": all_orders, "source": source, "fields": fields,
                       "full": full, "error": error}
        elif request is not None and (fields or error):
            request = deepcopy(request)
            request["fields"].update(fields)
            request["full"] = request["full"] or full
            request["error"] = error or (request["error"] if request["error"] == "conditional_address_request" else None)
            request["request_index"] = index
        elif request is not None and request["error"] == "target_order_required" and order_ids(text):
            request["order_ids"] = order_ids(text)
            request["error"] = None
            request["request_index"] = index
    return request


def complete_address(base, request):
    params = {} if request["full"] else {k: v for k, v in (base or {}).items() if k in FIELDS}
    params.update(request["fields"])
    missing = [k for k in FIELDS if k in REQUIRED and (not isinstance(params.get(k), str) or not params[k].strip())]
    params.setdefault("address_line_2", None)
    if params["address_line_2"] is not None and not isinstance(params["address_line_2"], str):
        missing.append("address_line_2")
    return params, missing
