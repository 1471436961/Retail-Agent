"""Small deterministic offline backends; none are bundled into agent/."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from urllib.parse import unquote


@dataclass
class FakeResponse:
    status_code: int
    body: dict
    headers: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise ValueError(f"HTTP {self.status_code}")


class FakeClientAPI:
    """Fresh instances start from the same synthetic customer/order/catalog."""

    def __init__(self, *, fail_after_write: bool = False):
        self.customers = {
            "customer_a": {
                "customer_id": "customer_a",
                "email": "a@example.test",
                "name": {"first_name": "Ada", "last_name": "Example"},
                "default_shipping_address": {"address_line_1": "1 Test St", "city": "Testville", "region": "CA", "country": "US", "postal_code": "90001"},
                "payment_methods": [{"id": "card_a", "source": "credit_card", "last_four": "0001"}],
                "order_ids": ["#TEST1"],
            },
            "customer_b": {
                "customer_id": "customer_b",
                "email": "b@example.test",
                "name": {"first_name": "Ben", "last_name": "Example"},
                "default_shipping_address": {"address_line_1": "9 Test St", "city": "Othercity", "region": "NY", "country": "US", "postal_code": "10001"},
                "payment_methods": [{"id": "card_b", "source": "credit_card", "last_four": "0002"}],
                "order_ids": ["#TEST2"],
            },
        }
        self.orders = {"#TEST1": {"order_id": "#TEST1", "customer_id": "customer_a", "status": "pending", "items": [{"item_id": "item_blue", "product_id": "product_mug", "price": 12.50}], "payments": []}}
        self.orders["#TEST2"] = {"order_id": "#TEST2", "customer_id": "customer_b", "status": "delivered", "items": [{"item_id": "item_blue", "product_id": "product_mug", "price": 10.00}], "payments": []}
        self.products = {"product_mug": {"product_id": "product_mug", "name": "Example mug", "items": [{"item_id": "item_blue", "product_id": "product_mug", "options": {"color": "blue"}, "price": 12.50, "available": True}]}}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.fail_after_write = fail_after_write

    def request(self, method: str, path: str, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if method == "POST" and path == "/v1/customers/search":
            for customer in self.customers.values():
                if isinstance(body, dict) and (body.get("email", "").casefold() == customer["email"].casefold() or (
                    body.get("first_name") == customer["name"]["first_name"]
                    and body.get("last_name") == customer["name"]["last_name"]
                    and body.get("postal_code") == customer["default_shipping_address"]["postal_code"]
                )):
                    return FakeResponse(200, {"customer_id": customer["customer_id"]})
            return FakeResponse(404, {"error": {"code": "customer_not_found", "message": "Not found"}})
        if method == "GET" and path.startswith("/v1/customers/"):
            customer_id = unquote(path.rsplit("/", 1)[1])
            customer = self.customers.get(customer_id)
            return FakeResponse(200, deepcopy(customer)) if customer else FakeResponse(404, {"error": {"code": "customer_not_found", "message": "Not found"}})
        if method == "PUT" and path.endswith("/default-shipping-address"):
            customer_id = unquote(path.split("/")[3])
            customer = self.customers.get(customer_id)
            if not customer:
                return FakeResponse(404, {"error": {"code": "customer_not_found", "message": "Not found"}})
            customer["default_shipping_address"] = deepcopy(body)
            if self.fail_after_write:
                raise TimeoutError("response lost after backend changed")
            return FakeResponse(200, {"customer_id": customer_id, "default_shipping_address": deepcopy(body)})
        if method == "GET" and path.startswith("/v1/orders/"):
            order = self.orders.get(unquote(path.rsplit("/", 1)[1]))
            return FakeResponse(200, deepcopy(order)) if order else FakeResponse(404, {"error": {"code": "order_not_found", "message": "Not found"}})
        if method == "GET" and path == "/v1/catalog/products":
            return FakeResponse(200, {"products": [{"product_id": product["product_id"], "name": product["name"]} for product in self.products.values()]})
        if method == "GET" and path.startswith("/v1/catalog/products/"):
            product = self.products.get(unquote(path.rsplit("/", 1)[1]))
            return FakeResponse(200, deepcopy(product)) if product else FakeResponse(404, {"error": {"code": "product_not_found", "message": "Not found"}})
        if method == "GET" and path.startswith("/v1/catalog/items/"):
            item_id = unquote(path.rsplit("/", 1)[1])
            for product in self.products.values():
                for item in product["items"]:
                    if item["item_id"] == item_id:
                        return FakeResponse(200, deepcopy(item))
            return FakeResponse(404, {"error": {"code": "item_not_found", "message": "Not found"}})
        return FakeResponse(405, {"error": {"code": "method_not_allowed", "message": "Unsupported by test fake"}})


class ScriptedGateway:
    """Feeds internal candidates; it does not pretend to be the tau2 gateway."""

    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = 0

    def next_candidate(self):
        self.calls += 1
        return self.candidates.pop(0)
