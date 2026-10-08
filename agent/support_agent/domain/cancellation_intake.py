"""Finite actual-user cancellation intake and per-charge display evidence."""
import json
import re
from decimal import Decimal, localcontext

from support_agent.domain.addresses import order_ids, starts_address_request
from support_agent.domain.payment_intake import starts_payment_request, method_label
from support_agent.domain.policies import cancellation_refund_basis, _methods, refund_timing_rule
from support_agent.domain.rules import allow, need
from support_agent.domain.money import display_exact_amount as _display


def starts_cancellation_request(text):
    intent = text.split("{", 1)[0]
    if re.search(r"\b(?:don't|do not|never|not to)\s+cancel\b|不要取消|别取消|不取消", intent, re.I):
        return False
    return bool(re.search(r"\b(cancel|cancellation)\b|取消", intent, re.I)
                and re.search(r"\border\b|订单|#[A-Za-z0-9_-]+", intent, re.I))


def _partial_order_scope(text):
    # Inspect scope, not the free-text reason or JSON reason value. The cancel
    # endpoint cancels an entire order; an item-scoped request cannot silently
    # become a whole-order proposal, including corrections to an active draft.
    intent = re.split(r"\bbecause\b|\breason\s*[:：=]|原因\s*[:：=]|因为|\{", text, maxsplit=1, flags=re.I)[0]
    # Exclusions/retained items narrow the whole-order action even without
    # "partial" or "only". Both singular and plural item wording is deliberate:
    # neither can be promoted to cancelling the whole order. Reason values
    # remain data; inspect only the request/scope before its reason delimiter.
    if re.search(r"\b(?:except(?:\s+for)?|excluding|exclude|keep|retain|leave)\b"
                 r"|保留|除(?:了|外)|不取消|留下|留着", intent, re.I):
        return True
    return bool(re.search(
        r"\b(?:partial(?:ly)?\b(?!\s+refund\b)|part\s+of|some\s+(?:of\s+)?(?:the\s+)?items?|"
        r"(?:only|just|one|a\s+single)\s+(?:the\s+)?(?:item(?:s)?\b|item_[\w-]+)|"
        r"cancel\s+(?:the\s+)?(?:[A-Za-z-]+\s+){0,3}items?\b)"
        r"|部分(?:订单|商品|取消)|取消(?:一部分|部分|其中|一件|一个商品)"
        r"|(?:只|仅)(?:取消)?\s*(?:商品|一件|一个|item_[\w-]+)|订单.*(?:中的|里|内).*商品",
        intent, re.I))


def _reason(text, *, initial):
    structured = re.search(r"(?:reason|原因)\s*[:：=]\s*(\{.*)", text, re.I | re.S)
    if structured:
        try:
            value = json.loads(structured[1])
        except ValueError:
            return None, "invalid_cancellation_json"
        if not isinstance(value, dict) or set(value) != {"reason"} or not isinstance(value["reason"], str):
            return None, "invalid_cancellation_fields"
        return value["reason"], None
    match = re.search(r"(?:\bbecause\b|\breason\s*[:：=]|原因\s*[:：=]|因为)\s*(.+)", text, re.I)
    if match:
        return match[1].strip(), None
    if initial:
        return None, None
    # Choice replies are finite; ordinary reads, identity input and unrelated
    # conversation do not become cancellation reasons or new request sources.
    if re.search(r"need|want|mistake|mind|cheaper|price|slow|delay|brand|不再需要|不想要|误|主意|价格|便宜|慢|品牌", text, re.I):
        return text.strip(), None
    return None, None


def request_from_history(history):
    request = None
    active = False
    for index, entry in enumerate(history):
        if entry["role"] != "user":
            continue
        from support_agent.semantics import frame, request as semantic_request
        if frame(entry) is not None:
            candidate = semantic_request(entry, index, 'cancellation')
            if candidate is not None:
                request, active = candidate, True
            elif frame(entry)['action'] not in {'clarify', 'respond', 'consent', 'read'}:
                active = False
            continue
        text = entry["content"]
        initial = starts_cancellation_request(text)
        if re.search(r"\b(?:don't|do not|never|not to)\s+cancel\b|不要取消|别取消|不取消", text, re.I):
            active = False
            continue
        from support_agent.domain.items_intake import starts_items_request, starts_exchange_request
        from support_agent.domain.returns_intake import starts_returns_request
        if not initial and (starts_address_request(text) or starts_payment_request(text)
                            or starts_items_request(text) or starts_exchange_request(text)
                            or starts_returns_request(text)):
            active = False
            continue
        if not initial and (request is None or not active):
            continue
        if initial:
            active = True
            ids = order_ids(text.split("{", 1)[0])
            reason, error = _reason(text, initial=True)
            if len(ids) != 1:
                error = error or ("single_order_required" if ids else "target_order_required")
            request = {"order_id": ids[0] if len(ids) == 1 else None, "reason": reason,
                       "error": error, "request_index": index}
        else:
            ids = order_ids(text)
            if request["order_id"] is None and len(ids) == 1 and re.fullmatch(r"\s*#[A-Za-z0-9_-]+\s*", text):
                request = {**request, "order_id": ids[0], "error": None if request["error"] in {"target_order_required", "single_order_required"} else request["error"], "request_index": index}
            reason, error = _reason(text, initial=False)
            if reason is not None or error:
                # A new reason replaces its previous format error, never an
                # independent target/condition/destination/business obstacle.
                retained_error = request["error"]
                if retained_error in {"invalid_cancellation_json", "invalid_cancellation_fields"}:
                    retained_error = None
                request = {**request, "reason": reason, "error": retained_error or error, "request_index": index}
                if request["order_id"] is None and request["error"] is None:
                    request["error"] = "target_order_required"
        if re.search(r"\b(if|unless|after|before|when)\b|如果|除非|之后|之前|先.*再", text, re.I):
            request = {**request, "error": "conditional_cancellation_request", "request_index": index}
        if re.search(r"refund\s+(?:it\s+)?to|different\s+card|退款到|退到|换.*退款|另.*卡", text, re.I):
            request = {**request, "error": "cancellation_original_destination_required", "request_index": index}
        if initial and (starts_address_request(text) or starts_payment_request(text) or re.search(r"\b(exchange|return|modify|change)\s+(?:the\s+)?items?\b|\b(exchange|return)\b|换货|退货|修改商品|更换商品", text.split("{", 1)[0], re.I)):
            request = {**request, "error": "mixed_business_request"}
        if re.search(r"partial\s+refund|withhold|keep\s+(?:part|some)|部分退款|扣除|保留.*款", text, re.I):
            request = {**request, "error": "full_original_refunds_required", "request_index": index}
        if _partial_order_scope(text):
            request = {**request, "error": "cancellation_whole_order_required", "request_index": index}
    return request


def refund_recap_rule(payments, methods):
    basis = cancellation_refund_basis(payments)
    if basis["decision"] != "allow":
        return basis
    if basis["details"]["recorded_refunds"]:
        return need("cancellation_refund_history_review", "Historical refunds require review before cancellation; do not refund or net them again.", "RF-01")
    saved = _methods(methods)
    charges = basis["details"]["charges"]
    # Exact sum of decimal representations of accepted charge amounts, solely
    # for display. No rounding, netting or guessed backend settlement formula.
    with localcontext() as context:
        context.prec = 700 + len(str(len(charges)))
        total = sum((Decimal(str(p["amount"])) for p in charges), Decimal(0))
    rows = []
    for index, charge in enumerate(charges, 1):
        method = saved.get(charge["payment_method_id"])
        timing = refund_timing_rule(method["source"])["details"]["timing"] if method else "channel timing unavailable"
        rows.append({"charge_index": index, **charge, "display_amount": _display(Decimal(str(charge["amount"]))),
                     "destination_label": method_label(method) if method else charge["payment_method_id"], "timing": timing})
    return allow("cancellation_refund_recapped", "Each recorded charge is refunded separately to its original method.", "RF-01", "RF-02",
                 details={"charges": charges, "rows": rows, "display_total": _display(total),
                          "display_method": "original_charges_exact_decimal_sum_no_rounding",
                          "settlement_verified": False})
