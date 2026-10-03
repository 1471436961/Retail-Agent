"""Six teaching read endpoints, with independent verification and ownership gates."""
from __future__ import annotations

import math
from urllib.parse import quote

from support_agent.adapters.client_api import request_object
from support_agent.domain.identity import matches_customer, search_body, verification_inputs

ORDER_STATUSES = {"pending", "pending (items modified)", "processed", "delivered", "cancelled", "exchange requested", "return requested"}
MAX_ORDERS_PER_LIST = 32  # Project safeguard, not a platform limit.


def identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty identifier is required")
    return quote(value, safe="")


def verify_customer(api, customer_id="", email="", first_name="", last_name="", postal_code="") -> dict:
    proof = verification_inputs(email, first_name, last_name, postal_code)
    if not isinstance(customer_id, str):
        raise ValueError("Customer ID must be a string")
    result = request_object(api, "POST", "/v1/customers/search", body=search_body(proof))
    found = result.get("customer_id")
    if not isinstance(found, str) or not found or (customer_id and found != customer_id):
        raise ValueError("Identity verification failed; no customer details were loaded")
    customer = request_object(api, "GET", f"/v1/customers/{identifier(found)}")
    if not matches_customer(customer, proof, found):
        raise ValueError("Identity verification failed; no verified details are available")
    return customer


def customer_order_ids(customer: dict) -> list[str]:
    ids = customer.get("order_ids")
    if not isinstance(ids, list) or any(not isinstance(v, str) or not v for v in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid customer order references")
    return ids


def validate_order(order: dict, customer_id: str, order_id: str) -> dict:
    if not isinstance(order, dict) or order.get("customer_id") != customer_id or order.get("order_id") != order_id:
        raise ValueError("Order ownership could not be verified")
    if order.get("status") not in ORDER_STATUSES or not isinstance(order.get("items"), list):
        raise ValueError("Invalid order state or items")
    if any(not isinstance(order.get(k), list) for k in ("payments", "fulfillments")):
        raise ValueError("Invalid order payments or fulfillments")
    for item in order["items"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in ("item_id", "product_id", "name")):
            raise ValueError("Invalid original order item")
        finite_amount(item.get("price"))
        options = item.get("options")
        if not isinstance(options, dict) or any(not isinstance(v, str) for v in options.values()):
            raise ValueError("Invalid original item options")
    for payment in order["payments"]:
        if not isinstance(payment, dict) or payment.get("transaction_type") not in {"payment", "refund"} or not isinstance(payment.get("payment_method_id"), str) or not payment["payment_method_id"]:
            raise ValueError("Invalid payment record")
        finite_amount(payment.get("amount"))
    for fulfillment in order["fulfillments"]:
        if not isinstance(fulfillment, dict) or any(not isinstance(fulfillment.get(k), list) or any(not isinstance(v, str) for v in fulfillment[k]) for k in ("item_ids", "tracking_id")):
            raise ValueError("Invalid fulfillment record")
    return order


def finite_amount(value):
    if type(value) not in (int, float):
        raise ValueError("Invalid amount type")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Invalid amount value")


def _owned_order(api, customer: dict, order_id: str) -> dict:
    identifier(order_id)
    if order_id not in customer_order_ids(customer):
        raise ValueError("That order is outside the verified customer's order references")
    order = request_object(api, "GET", f"/v1/orders/{identifier(order_id)}")
    return validate_order(order, customer["customer_id"], order_id)


def get_order(api, order_id: str, **verification) -> dict:
    return _owned_order(api, verify_customer(api, **verification), order_id)


def list_customer_orders(api, status: str = "", **verification) -> dict:
    if not isinstance(status, str) or (status and status not in ORDER_STATUSES):
        raise ValueError("Unknown order status; no status is inferred")
    customer = verify_customer(api, **verification)
    ids = customer_order_ids(customer)
    if len(ids) > MAX_ORDERS_PER_LIST:
        raise ValueError("Too many orders for one request; please specify an order ID")
    orders = [_owned_order(api, customer, order_id) for order_id in ids]
    return {"customer_id": customer["customer_id"], "orders": [o for o in orders if not status or o["status"] == status]}


def validate_item(item: dict, expected_id: str | None = None) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"] or (expected_id is not None and item["item_id"] != expected_id):
        raise ValueError("Invalid catalog item ID")
    if type(item.get("available")) is not bool or not isinstance(item.get("options"), dict) or any(not isinstance(v, str) for v in item["options"].values()):
        raise ValueError("Invalid catalog availability or options")
    finite_amount(item.get("price"))
    return item


def validate_catalog(body: dict, name: str, arguments: dict) -> dict:
    if name == "list_products":
        products = body.get("products")
        if not isinstance(products, list) or any(not isinstance(p, dict) or not isinstance(p.get("product_id"), str) or not p["product_id"] or not isinstance(p.get("name"), str) for p in products):
            raise ValueError("Invalid product collection")
        if len({p["product_id"] for p in products}) != len(products):
            raise ValueError("Repeated product IDs")
    elif name == "get_product":
        if body.get("product_id") != arguments["product_id"] or not isinstance(body.get("name"), str) or not isinstance(body.get("items"), list):
            raise ValueError("Invalid product details")
        for item in body["items"]:
            validate_item(item)
        if len({i["item_id"] for i in body["items"]}) != len(body["items"]):
            raise ValueError("Repeated catalog variant IDs")
    elif name == "get_item":
        validate_item(body, arguments["item_id"])
    return body


def list_products(api, **verification) -> dict:
    verify_customer(api, **verification)
    return validate_catalog(request_object(api, "GET", "/v1/catalog/products"), "list_products", {})


def get_product(api, product_id: str, **verification) -> dict:
    path = identifier(product_id)
    verify_customer(api, **verification)
    return validate_catalog(request_object(api, "GET", f"/v1/catalog/products/{path}"), "get_product", {"product_id": product_id})


def get_item(api, item_id: str, **verification) -> dict:
    path = identifier(item_id)
    verify_customer(api, **verification)
    return validate_catalog(request_object(api, "GET", f"/v1/catalog/items/{path}"), "get_item", {"item_id": item_id})
