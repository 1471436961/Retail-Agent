"""Catch changes to the bundled teaching contract before adding business tools."""

import json
import unittest
from pathlib import Path


SPEC = Path(__file__).resolve().parents[1] / "materials" / "client_api" / "openapi.yaml"


class ContractBaselineTests(unittest.TestCase):
    def test_operation_inventory_and_retry_guards(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        operations = [(method.upper(), path, details)
                      for path, methods in spec["paths"].items()
                      for method, details in methods.items()
                      if method.lower() in {"get", "post", "put", "patch", "delete"}]
        self.assertEqual(len(operations), 14)
        self.assertEqual(sum(not details["x-api-mutates-state"] for _, _, details in operations), 6)
        self.assertEqual(sum(details["x-api-mutates-state"] for _, _, details in operations), 8)
        for method, path, details in operations:
            with self.subTest(method=method, path=path):
                expected_retry = "forbidden" if details["x-api-mutates-state"] else "allowed"
                self.assertEqual(details["x-api-automatic-retries"], expected_retry)
                self.assertEqual(details["x-api-consistency"], "strong")
                self.assertEqual(details["x-api-pagination"], "none")
                self.assertEqual(details["x-api-request-body-max-bytes"], 1048576)
                self.assertEqual(details["x-api-response-body-max-bytes"], 4194304)
                expected_success = "201" if path.endswith("/transfers") else "200"
                self.assertEqual(set(details["responses"]), {expected_success, "400", "404", "405", "409", "413", "422", "502"})
        search = spec["paths"]["/v1/customers/search"]["post"]
        self.assertFalse(search["x-api-mutates-state"])
        for path in ("/v1/orders/{order_id}/item-modifications", "/v1/orders/{order_id}/returns", "/v1/orders/{order_id}/exchanges"):
            self.assertEqual(spec["paths"][path]["post"]["x-api-automatic-retries"], "forbidden")

    def test_closed_values_match_the_contract(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        schemas = spec["components"]["schemas"]
        status = spec["paths"]["/v1/orders/{order_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["status"]
        self.assertEqual(set(status["enum"]), {"pending", "processed", "pending (items modified)", "delivered", "cancelled", "return requested", "exchange requested"})
        self.assertEqual(set(schemas["OrderCancellation"]["properties"]["reason"]["enum"]), {"no longer needed", "ordered by mistake"})
        self.assertEqual(set(schemas["OrderPayment"]["properties"]["transaction_type"]["enum"]), {"payment", "refund"})
        self.assertEqual({schemas[name]["properties"]["source"]["const"] for name in ("CreditCard", "GiftCard", "Paypal")}, {"credit_card", "gift_card", "paypal"})


if __name__ == "__main__":
    unittest.main()
