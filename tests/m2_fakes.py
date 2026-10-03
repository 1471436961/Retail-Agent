"""Teaching-shaped synthetic data; no material fixtures or production records."""
from copy import deepcopy

from fakes import FakeClientAPI, FakeResponse


class ReadFake(FakeClientAPI):
    def __init__(self):
        super().__init__()
        self.customers["customer_a"]["name"]["first_name"] = "Alice"
        self.customers["customer_a"]["default_shipping_address"]["postal_code"] = "10001"
        for order in self.orders.values():
            customer = self.customers[order["customer_id"]]
            order["shipping_address"] = deepcopy(customer["default_shipping_address"])
            order["fulfillments"] = []
            for item in order["items"]:
                item.update(name="Example mug", options={"color": "blue"})

    def request(self, method, path, *, body=None):
        if method == "POST" and path == "/v1/customers/search" and body and "first_name" in body:
            self.calls.append((method, path, deepcopy(body)))
            for customer in self.customers.values():
                name = customer["name"]
                if (name["first_name"].casefold() == body["first_name"].casefold()
                        and name["last_name"].casefold() == body["last_name"].casefold()
                        and customer["default_shipping_address"]["postal_code"].casefold() == body["postal_code"].casefold()):
                    return FakeResponse(200, {"customer_id": customer["customer_id"]})
            return FakeResponse(404, {"error": {"code": "customer_not_found"}})
        return super().request(method, path, body=body)
