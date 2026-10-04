"""Payment, destination and reason rules over accepted facts; no money movement."""
from support_agent.domain.money import finite_amount, finite_number
from support_agent.domain.rules import allow, deny, identifier, input_error, need

PAYMENT_SOURCES = frozenset({"credit_card", "paypal", "gift_card"})


def _methods(records):
    if not isinstance(records, list):
        raise ValueError("Saved payment records are required")
    methods = {}
    for method in records:
        if (not isinstance(method, dict) or not identifier(method.get("id"))
                or not isinstance(method.get("source"), str) or method["source"] not in PAYMENT_SOURCES
                or method["id"] in methods):
            raise ValueError("Invalid or repeated saved payment method")
        required = {"id", "source"} | ({"balance"} if method["source"] == "gift_card" else
                                       {"brand", "last_four"} if method["source"] == "credit_card" else set())
        if set(method) != required:
            raise ValueError("Saved payment method fields do not match the contract")
        if method["source"] == "gift_card":
            finite_amount(method.get("balance"))
        elif method["source"] == "credit_card" and any(not isinstance(method.get(k), str) for k in ("brand", "last_four")):
            raise ValueError("Invalid credit card record")
        methods[method["id"]] = method
    return methods


def _payments(records):
    if not isinstance(records, list):
        raise ValueError("Payment history is required")
    for payment in records:
        if (not isinstance(payment, dict) or set(payment) != {"transaction_type", "amount", "payment_method_id"}
                or not isinstance(payment["transaction_type"], str) or payment["transaction_type"] not in {"payment", "refund"}
                or not identifier(payment["payment_method_id"])):
            raise ValueError("Invalid payment history entry")
        finite_amount(payment["amount"])
    return records


def settlement_method_rule(action, payment_methods, payment_method_id, amount, *, current_payment_method_id=None) -> dict:
    """amount is an already-resolved full order charge or signed difference.

    Payment switching requires a proven current method supplied by the caller;
    the last history entry does not establish it. No full-total formula is guessed.
    """
    if not isinstance(action, str):
        return input_error("invalid_action", "Action must be a string.", "PY-01")
    if action not in {"payment_method", "modify_items", "exchange"}:
        return deny("unsupported_settlement_action", "Cancellation and return destinations have separate rules.", "PY-01", "RT-02")
    if isinstance(payment_method_id, (list, tuple)):
        return deny("single_method_required", "Select exactly one saved method; split payment is unsupported.", "PY-01", "IT-02")
    if payment_method_id is None or isinstance(payment_method_id, str) and not payment_method_id.strip():
        return need("payment_method_required", "Choose one saved payment method, including for zero difference.", "PY-01", "IT-02", "EX-01")
    if not identifier(payment_method_id):
        return input_error("invalid_payment_method_id", "Payment method ID must be a nonempty string.", "PY-01")
    try:
        methods = _methods(payment_methods)
    except (TypeError, ValueError):
        return need("payment_facts_required", "Refresh complete saved payment records and balances.", "PY-01", "U3")
    if payment_method_id not in methods:
        return deny("payment_method_not_saved", "A new or unknown method cannot be added by this service.", "PY-01", "BN-01")
    if amount is None:
        return need("amount_required", "The full order amount or complete signed difference must be known.", "MO-01", "U3")
    try:
        finite_number(amount)
    except (TypeError, ValueError):
        return input_error("invalid_amount", "Amount must be a finite number without coercion.", "MO-01", "U3")
    if action == "payment_method":
        if amount < 0:
            return input_error("invalid_order_amount", "A full order charge cannot be negative.", "MO-01")
        if current_payment_method_id is not None and not isinstance(current_payment_method_id, str):
            return input_error("invalid_current_payment_method_id", "Current method ID must be a string.", "PY-01")
        if not identifier(current_payment_method_id) or current_payment_method_id not in methods:
            return need("current_payment_method_required", "Establish the current method from accepted facts; do not infer it from history position.", "PY-01")
        if current_payment_method_id == payment_method_id:
            return deny("same_payment_method", "The replacement method must differ from the current method.", "PY-01")
    method = methods[payment_method_id]
    if method["source"] == "gift_card" and amount > 0 and method["balance"] < amount:
        return deny("insufficient_gift_card", "The gift card must cover the entire charge; another method cannot top it up.", "PY-01", "IT-02")
    return allow("settlement_method_eligible", "One existing method can settle this amount; no charge or refund has occurred.", "PY-01", "IT-02", "EX-01",
                 details={"payment_method_id": payment_method_id, "amount": amount,
                          "direction": "charge" if amount > 0 else "refund" if amount < 0 else "zero",
                          "amount_basis": "provided_full_order_total" if action == "payment_method" else "provided_price_difference",
                          "settlement_verified": False})


def cancellation_refund_basis(payments) -> dict:
    """Keep one basis row per original charge, even for the same instrument.

    Existing refunds remain separate. This is not a remaining-balance calculation,
    an instruction to refund again, an aggregate quote, or a settlement receipt.
    The inspected upstream cancellation loop copies all history entries; that
    implementation does not establish current RF-01 semantics. Retain only
    charge entries as the basis, rather than copying prior refunds into it.
    """
    try:
        records = _payments(payments)
    except (TypeError, ValueError):
        return need("payment_history_required", "Refresh the original charge/refund records.", "RF-01", "MO-01")
    charges = [p for p in records if p["transaction_type"] == "payment"]
    if not charges:
        return need("original_charges_required", "No original charge basis is available; do not assume zero.", "RF-01")
    return allow("per_charge_basis", "Each original charge retains its amount and original destination.", "RF-01",
                 details={"charges": charges, "recorded_refunds": [p for p in records if p["transaction_type"] == "refund"],
                          "aggregate_amount": None, "aggregation_contract_verified": False, "settlement_verified": False})


def return_destination_rule(payment_methods, payments, payment_method_id, *, opening_payment_methods=None) -> dict:
    """Opening snapshot must be grounded in the future workflow's source chain.

    A late current profile does not establish historical gift-card eligibility.
    The caller owns provenance/turn validation; no boolean 'eligible' is accepted.
    Original payment destinations are derived only from charge records.
    """
    if payment_method_id is not None and not isinstance(payment_method_id, str):
        return input_error("invalid_payment_method_id", "Refund destination ID must be a string.", "RT-02")
    try:
        methods = _methods(payment_methods)
        records = _payments(payments)
        opening = _methods(opening_payment_methods) if opening_payment_methods is not None else None
    except (TypeError, ValueError):
        return need("refund_destination_facts_required", "Refresh saved instruments and the original charge records.", "RT-02", "U3")
    original_ids = list(dict.fromkeys(p["payment_method_id"] for p in records if p["transaction_type"] == "payment"))
    if not original_ids:
        return need("original_charges_required", "Original payment destinations cannot be established from refunds alone.", "RT-02")
    gift_ids = [key for key, method in methods.items() if method["source"] == "gift_card" and opening is not None
                and key in opening and opening[key]["source"] == "gift_card"]
    candidates = list(dict.fromkeys(original_ids + gift_ids))
    if not identifier(payment_method_id):
        return need("refund_destination_choice_required", "The customer must select a legal refund destination.", "RT-02",
                    details={"candidate_ids": candidates, "opening_snapshot_available": opening is not None})
    if payment_method_id in original_ids:
        return allow("original_refund_destination", "The selected method paid for this order.", "RT-02",
                     details={"refund_payment_method_id": payment_method_id, "basis": "original_charge"})
    method = methods.get(payment_method_id)
    if method is None:
        return deny("refund_method_not_saved", "A new instrument cannot be a fallback refund destination.", "RT-02", "BN-01")
    if method["source"] != "gift_card":
        return deny("unsupported_return_destination", "Return refunds cannot redirect to a different card or unrelated PayPal.", "RT-02")
    if opening is None:
        return need("opening_snapshot_required", "A current gift card does not prove it existed before the return request opened.", "RT-02", "U7")
    if payment_method_id not in gift_ids:
        return deny("gift_card_not_eligible_at_opening", "A gift card added after opening is ineligible for this return.", "RT-02", "U7")
    return allow("opening_gift_card_destination", "The selected gift card is present in the supplied opening and current records.", "RT-02", "U7",
                 details={"refund_payment_method_id": payment_method_id, "basis": "opening_profile"})


def refund_timing_rule(source) -> dict:
    if not isinstance(source, str) or source not in PAYMENT_SOURCES:
        return need("refund_channel_required", "The channel must be known before giving a timing estimate.", "RF-02")
    return allow("refund_timing_policy", "This is channel policy, not evidence that money has arrived.", "RF-02",
                 details={"timing": "immediate" if source == "gift_card" else "3-6 business days", "settlement_verified": False})


def cancellation_reason_rule(reason) -> dict:
    """Conservative semantic normalization of a reason, never cancellation consent."""
    if reason is not None and not isinstance(reason, str):
        return input_error("invalid_cancellation_reason", "Cancellation reason must be a string.", "CA-01")
    if reason is None or not reason.strip():
        return need("cancellation_reason_required", "Ask why the customer wants to cancel.", "CA-01", "CA-02")
    aliases = {"no longer needed": ("no longer needed", "i no longer need it", "i do not need it anymore", "i don't need it anymore", "i don't want it anymore", "i do not want it anymore", "不想要了", "不需要了", "changed my mind", "i changed my mind", "不再需要", "改变主意"),
               "ordered by mistake": ("ordered by mistake", "i ordered by mistake", "placed the order by mistake", "it was ordered by mistake", "i placed it by mistake", "误下单", "下错单", "误购")}
    text = " ".join(reason.strip().rstrip(".。!").casefold().split())
    for canonical, values in aliases.items():
        if text in values:
            return allow("supported_cancellation_reason", "The reason maps to a documented value; a complete confirmed proposal is still required.", "CA-01", "CA-02",
                         details={"reason": canonical})
    return need("clarify_cancellation_reason", "Clarify the reason; price, delay or ambiguous wording must not be relabeled automatically.", "CA-01")
