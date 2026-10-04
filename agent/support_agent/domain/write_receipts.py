"""Normalize documented receipts, without asserting settlement or shipment."""
import json
from collections import Counter

from support_agent.domain.orders import PENDING_ACTIONS
from support_agent.domain.catalog import _original_groups
from support_agent.domain.policies import _payments
from support_agent.domain.money import finite_number
from support_agent.domain.rules import allow, need


def fulfillment_rule(order, action):
    """A tracking label alone is not a shipped flag.

    Nonempty fulfillment item records on a pending order require investigation:
    the API cannot establish whether they mean reservation or actual shipment.
    Neither case permits silently assuming the unshipped condition in S17.
    """
    if action not in PENDING_ACTIONS or order["status"] != "pending":
        return allow("fulfillment_not_pending", "Exact state eligibility is assessed separately.", "U6")
    if "shipped" in order or any(set(f) != {"item_ids", "tracking_id"} for f in order["fulfillments"]):
        return need("undocumented_fulfillment_fact", "Unexpected shipment/fulfillment fields need an applicable contract; do not infer the unshipped prerequisite.", "U6")
    fulfilled = [i for f in order["fulfillments"] for i in f["item_ids"]]
    if Counter(fulfilled) - Counter(i["item_id"] for i in order["items"]):
        return need("fulfillment_items_conflict", "Fulfillment units disagree with this order; stop and investigate.", "U6")
    if fulfilled:
        return need("fulfillment_requires_review", "Pending state and fulfillment item records do not establish the unshipped prerequisite.", "U6", "ST-01")
    return allow("no_fulfillment_conflict", "No item fulfillment conflict is visible; tracking labels do not prove shipment.", "U6")


def _normalize_receipt(spec, body):
    """An unusable 2xx receipt is Unknown, never a definite failed write."""
    body = json.loads(json.dumps(body, allow_nan=False))
    action, target, params = spec["action"], spec["target"], spec["parameters"]
    fields = {
        "default_shipping_address": {"customer_id", "default_shipping_address"},
        "shipping_address": {"order_id", "shipping_address"},
        "payment_method": {"order_id", "payments"},
        "cancel": {"order_id", "status", "cancellation", "payments"},
        "modify_items": {"order_id", "status", "items", "payments"},
        "exchange": {"order_id", "status", "exchange"},
        "return": {"order_id", "status", "return_request"},
    }[action]
    key = "customer_id" if action == "default_shipping_address" else "order_id"
    if not isinstance(body, dict) or set(body) != fields or body[key] != target[key]:
        raise ValueError("Receipt fields or target do not match the operation")
    if "payments" in body:
        _payments(body["payments"])
    if action in {"default_shipping_address", "shipping_address"}:
        field = "default_shipping_address" if action == "default_shipping_address" else "shipping_address"
        if not isinstance(body[field], dict):
            raise ValueError("Address receipt must be an object")
        body[field].setdefault("address_line_2", None)
        if body[field] != params:
            raise ValueError("Receipt address differs from the complete proposal")
    elif action == "cancel":
        if body["status"] != "cancelled" or body["cancellation"] != params:
            raise ValueError("Cancellation receipt differs from the request")
    elif action == "modify_items":
        # Reuse the order-item schema; ownership/status of the readback are
        # checked separately, rather than treating this partial body as an order.
        _original_groups(body["items"])
        if any(set(i) != {"item_id", "product_id", "name", "price", "options"} for i in body["items"]):
            raise ValueError("Unexpected order item receipt fields")
        if body["status"] != "pending (items modified)":
            raise ValueError("Item modification receipt has an unexpected state")
    elif action == "exchange":
        expected = {**params, "price_difference": spec["amount"]["value"]}
        if not isinstance(body["exchange"], dict):
            raise ValueError("Exchange receipt must be an object")
        finite_number(body["exchange"].get("price_difference"))
        if body["status"] != "exchange requested" or body["exchange"] != expected:
            raise ValueError("Exchange receipt differs from the complete proposal")
    elif action == "return":
        request = body["return_request"]
        if (body["status"] != "return requested" or not isinstance(request, dict)
                or set(request) != {"item_ids", "refund_payment_method_id"}
                or not isinstance(request["item_ids"], list)
                or any(not isinstance(i, str) for i in request["item_ids"])
                or Counter(request["item_ids"]) != Counter(params["item_ids"])
                or request["refund_payment_method_id"] != params["refund_payment_method_id"]):
            raise ValueError("Return receipt differs from selected occurrences or destination")
    return body


def normalize_receipt(spec, body):
    """Expose one controlled error type for malformed or unusable receipts."""
    try:
        return _normalize_receipt(spec, body)
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError("Malformed operation receipt") from exc


def receipt_matches_readback(spec, receipt, facts, before):
    """Require a valid receipt AND a subsequent owned strong read.

    A matching address alone cannot prove a write was sent or succeeded. This
    compares observable effects, not refund arrival or hidden ledger semantics.
    Business quote/payment validation is a separate mandatory runtime gate.
    """
    receipt = normalize_receipt(spec, receipt)
    record = facts["customer"] if spec["action"] == "default_shipping_address" else facts["order"]
    key = "customer_id" if spec["action"] == "default_shipping_address" else "order_id"
    observed = json.loads(json.dumps(record, allow_nan=False))
    for field in ("shipping_address", "default_shipping_address"):
        if field in receipt and isinstance(observed.get(field), dict):
            observed[field].setdefault("address_line_2", None)
    if observed[key] != receipt[key] or any(observed.get(k) != v for k, v in receipt.items() if k != key):
        return False
    if spec["action"] in {"shipping_address", "payment_method"} and record["status"] != "pending":
        return False
    if spec["action"] == "modify_items":
        original = json.loads(json.dumps(before["order"]["items"], allow_nan=False))
        targets = {v["item"]["item_id"]: v["item"] for v in before["catalog"]}
        for pair in spec["parameters"]["replacements"]:
            old = next((i for i in original if i["item_id"] == pair["existing_item_id"]), None)
            target = targets.get(pair["replacement_item_id"])
            if old is None or target is None:
                return False
            old.update({k: target[k] for k in ("item_id", "price", "options")})
        if receipt["items"] != original:
            return False
    if spec["action"] == "payment_method":
        prior = before["order"]["payments"]
        rows = receipt["payments"]
        expected = {"transaction_type": "payment", "amount": spec["amount"]["value"],
                    "payment_method_id": spec["parameters"]["payment_method_id"]}
        # At least the new complete charge must be observable after the prior
        # history. Original refund semantics still belong to PY-02/M4 validation.
        refunds = [{"transaction_type": "refund", "amount": p["amount"], "payment_method_id": p["payment_method_id"]}
                   for p in spec["amount"]["refund_rows"]]
        keys = lambda data: Counter((p["transaction_type"], p["amount"], p["payment_method_id"]) for p in data)
        if rows[:len(prior)] != prior or keys(rows[len(prior):]) != keys([expected] + refunds):
            return False
    if spec["action"] == "cancel":
        prior = before["order"]["payments"]
        refunds = [{"transaction_type": "refund", "amount": p["amount"], "payment_method_id": p["payment_method_id"]}
                   for p in spec["amount"]["rows"]]
        keys = lambda data: Counter((p["transaction_type"], p["amount"], p["payment_method_id"]) for p in data)
        rows = receipt["payments"]
        if rows[:len(prior)] != prior or keys(rows[len(prior):]) != keys(refunds):
            return False
    if spec["action"] == "modify_items":
        prior = before["order"]["payments"]
        rows, difference = receipt["payments"], spec["amount"]["value"]
        if rows[:len(prior)] != prior:
            return False
        if difference:
            expected = {"transaction_type": "payment" if difference > 0 else "refund", "amount": abs(difference),
                        "payment_method_id": spec["parameters"]["payment_method_id"]}
            if rows[len(prior):] != [expected]:
                return False
    return True
