"""Finite payment-choice grammar over actual user text and saved facts only."""
import json
import re
from copy import deepcopy

from support_agent.domain.addresses import order_ids, starts_address_request
from support_agent.domain.policies import _methods, _payments, settlement_method_rule
from support_agent.domain.rules import allow, deny, need


def starts_payment_request(text):
    intent = text.split("{", 1)[0]
    return (not starts_address_request(intent) and bool(re.search(r"payment|pay(?:\s+order)?\b|支付|付款", intent, re.I))
            and bool(re.search(r"\b(change|switch|use|pay|update|replace)\b|更换|切换|改用|修改|换成|使用", intent, re.I)))


def _selection(text, *, initial=False):
    structured = re.search(r"(?:payment|支付)\s*[:：=]\s*(\{.*\})", text, re.I | re.S)
    if structured:
        try:
            value = json.loads(structured[1])
        except (TypeError, ValueError):
            return None, "invalid_payment_json"
        if not isinstance(value, dict) or set(value) != {"payment_method_id"}:
            return None, "unsupported_payment_fields"
        if isinstance(value["payment_method_id"], list):
            return None, "single_method_required"
        if not isinstance(value["payment_method_id"], str) or not value["payment_method_id"].strip():
            return None, "invalid_payment_method_id"
        return {"query":value["payment_method_id"], "fallback":None, "exact":True}, None
    if re.search(r"split|two cards|both cards|half.*half|分摊|两张|混合|部分.*支付|抵扣", text, re.I):
        return None, "single_method_required"
    explicit = re.search(r"payment_method_id\s*[:：=]\s*([^\s,;，；]+)", text, re.I)
    if explicit:
        return {"query":explicit[1], "fallback":None, "exact":True}, None
    match = re.search(r"(?:\bto\b|\bwith\b|\buse\b|改用|换成|使用)\s*(.+)", text, re.I)
    query = match[1] if match else "" if initial else text
    query = query.strip().rstrip(".!。！")
    fallback = re.fullmatch(r"(.+?)\s+if\s+(?:it\s+is\s+|the\s+balance\s+is\s+)?(?:sufficient|enough)(?:\s+for\s+the\s+(?:whole|entire)\s+order)?[,;]?\s+(?:otherwise|else)\s+(?:use\s+)?(.+)", query, re.I)
    chinese = re.fullmatch(r"(.+?)(?:如果)?余额足够(?:支付整单)?[，,；;]?\s*否则(?:使用|用)?(.+)", query)
    fallback = fallback or chinese
    if fallback:
        return {"query":fallback[1].strip(), "fallback":fallback[2].strip(), "exact":False}, None
    if re.search(r"\b(if|unless|after|before|then|first)\b|如果|除非|之后|之前|先.*再|余额足够", text, re.I):
        return None, "conditional_payment_request"
    if not query or query.casefold() in {"yes", "no", "confirm", "retry", "try again", "确认", "重试", "取消", "谢谢"}:
        return None, None
    return {"query":query, "fallback":None, "exact":False}, None


def request_from_history(history):
    request = None
    for index, entry in enumerate(history):
        if entry["role"] != "user":
            continue
        text = entry["content"]
        if starts_payment_request(text):
            ids = order_ids(text.split("{", 1)[0])
            selection, error = _selection(text, initial=True)
            if re.search(r"\b(cancel|return|exchange|items?)\b|取消订单|退货|换货|商品", text.split("{",1)[0], re.I):
                error = "mixed_business_request"
            if not ids:
                if request is not None and selection:
                    request = {**request, "selection":selection, "error":error, "request_index":index}
                    continue
                error = error or "target_order_required"
            elif len(ids) != 1:
                error = error or "single_order_required"
            request = {"order_id":ids[0] if len(ids) == 1 else None, "selection":selection, "error":error, "request_index":index}
        elif request is not None and not starts_address_request(text):
            # Only explicit correction/ID/source/brand language contributes a
            # choice. Assent, silence and unrelated narrative cannot select it.
            if request["order_id"] is None and len(order_ids(text)) == 1:
                request = {**request, "order_id":order_ids(text)[0], "error":None, "request_index":index}
                continue
            if selection_text(text):
                selection, error = _selection(text)
                if selection or error:
                    request = deepcopy(request)
                    request.update(selection=selection, error=error or (request["error"] if request["error"] == "conditional_payment_request" else None), request_index=index)
    return request


def selection_text(text):
    """Recognize choice replies, excluding brands inside unrelated field text."""
    return bool(re.match(r"^(?:no[,\s]+|不[,，]?)?(?:use\b|to\b|with\b|改用|换成|使用|payment_method_id\s*[:：=]|支付\s*[:：=])", text.strip(), re.I)
                or re.fullmatch(r"(?:paypal|visa|mastercard|amex|gift card|礼品卡)(?:\s+ending\s+\d{4})?[.!。！]?", text.strip(), re.I)
                or re.fullmatch(r"[\w-]+", text.strip()) and "_" in text)


def current_charge_rule(payments, methods):
    try:
        payments, methods = _payments(payments), _methods(methods)
    except (TypeError, ValueError):
        return need("payment_facts_required", "Complete saved methods and payment history are required.", "PY-01")
    # Fixed upstream requires exactly one original payment for this operation.
    # Historical refunds/multiple charges cannot establish its current method.
    if len(payments) != 1 or payments[0]["transaction_type"] != "payment":
        return need("current_payment_basis_unsupported", "Payment switching supports one original charge; historical rows are not netted or treated as current by position.", "PY-02")
    charge = payments[0]
    if charge["payment_method_id"] not in methods:
        return need("current_payment_method_required", "The original instrument must be present in accepted saved-method facts.", "PY-01")
    return allow("current_payment_established", "The one original charge establishes the full amount and original instrument.", "PY-02", details={"charge":charge})


def choose_method(methods, selection):
    methods = _methods(methods)
    if selection is None:
        return need("payment_method_required", "Please choose one of your saved methods.", "PY-01", details={"candidate_ids":list(methods)})
    query = selection["query"]
    if query in methods:
        return allow("saved_method_selected", "An exact saved ID was selected.", "PY-01", details={"payment_method_id":query})
    if selection["exact"]:
        return deny("payment_method_not_saved", "This ID is not a saved method; adding an instrument is unsupported.", "PY-01", "BN-01")
    if sum(bool(re.search(pattern, query, re.I)) for pattern in (r"gift[ _-]?card|礼品卡", r"paypal", r"\bvisa\b", r"\bmastercard\b", r"\bamex\b|american express")) > 1:
        return deny("single_method_required", "Select one instrument; distinct sources/brands are not combined.", "PY-01")
    source = "gift_card" if re.search(r"gift[ _-]?card|礼品卡", query, re.I) else "paypal" if re.search(r"paypal", query, re.I) else None
    brand = next((v for v in ("visa", "mastercard", "amex", "american express") if re.search(r"\b"+v+r"\b", query, re.I)), None)
    last_four = re.findall(r"(?<!\d)\d{4}(?!\d)", query)
    if len(last_four) > 1:
        return need("payment_selection_ambiguous", "Multiple endings require a single explicit choice.", "PY-01")
    if source is None and brand is None and not last_four:
        return need("payment_method_not_identified", "Please select a saved ID, source or unambiguous brand/last four; I will not infer an unknown ID.", "PY-01")
    matches = [m["id"] for m in methods.values() if (source is None or m["source"] == source)
               and (brand is None or m.get("brand", "").casefold() == brand)
               and (not last_four or m.get("last_four") == last_four[0])]
    if len(matches) != 1:
        return need("payment_selection_ambiguous" if matches else "payment_method_not_saved", "Please choose one matching saved method; no new method can be added.", "PY-01", details={"candidate_ids":matches})
    return allow("saved_method_selected", "One saved method matches the customer's selection.", "PY-01", details={"payment_method_id":matches[0]})


def resolve_choice(methods, selection, charge):
    choice = choose_method(methods, selection)
    if choice["decision"] != "allow":
        return choice
    selected = choice["details"]["payment_method_id"]
    eligibility = settlement_method_rule("payment_method", methods, selected, charge["amount"], current_payment_method_id=charge["payment_method_id"])
    if selection and selection["fallback"]:
        if _methods(methods)[selected]["source"] != "gift_card":
            return need("unsupported_payment_condition", "The supported fallback condition is whole-order gift-card sufficiency.", "PY-01")
        if eligibility["code"] == "insufficient_gift_card":
            fallback = choose_method(methods, {"query":selection["fallback"], "fallback":None, "exact":False})
            if fallback["decision"] != "allow":
                return fallback
            selected = fallback["details"]["payment_method_id"]
            eligibility = settlement_method_rule("payment_method", methods, selected, charge["amount"], current_payment_method_id=charge["payment_method_id"])
            eligibility["details"]["fallback_used"] = True
    return eligibility


def method_label(method):
    if method["source"] == "credit_card":
        return f'{method["brand"]} ending {method["last_four"]} ({method["id"]})'
    if method["source"] == "gift_card":
        return f'gift card {method["id"]}, balance {method["balance"]}'
    return f'PayPal ({method["id"]})'
