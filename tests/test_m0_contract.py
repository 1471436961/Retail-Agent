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

    def test_money_fields_declare_numbers_not_strings_or_booleans(self):
        schemas = json.loads(SPEC.read_text(encoding="utf-8"))["components"]["schemas"]
        for schema_name, field in (("GiftCard", "balance"), ("CatalogItem", "price"),
                                   ("OrderItem", "price"), ("OrderPayment", "amount"),
                                   ("OrderExchange", "price_difference")):
            with self.subTest(schema=schema_name, field=field):
                declaration = schemas[schema_name]["properties"][field]
                self.assertEqual(declaration["type"], "number")
                self.assertNotIn("anyOf", declaration)
                self.assertIn(field, schemas[schema_name]["required"])

    def test_item_lists_preserve_duplicates_without_line_or_quantity_fields(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        replacement = spec["components"]["schemas"]["ItemReplacement"]
        self.assertEqual(set(replacement["properties"]), {"existing_item_id", "replacement_item_id"})
        self.assertEqual(set(replacement["required"]), set(replacement["properties"]))
        self.assertIs(replacement["additionalProperties"], False)
        for operation, field in (("item-modifications", "replacements"),
                                 ("exchanges", "replacements"), ("returns", "item_ids")):
            with self.subTest(operation=operation):
                request = spec["paths"][f"/v1/orders/{{order_id}}/{operation}"]["post"]["requestBody"]["content"]["application/json"]["schema"]
                sequence = request["properties"][field]
                self.assertEqual(sequence["type"], "array")
                self.assertEqual(sequence["minItems"], 1)
                self.assertFalse(sequence.get("uniqueItems", False))
                self.assertNotIn("quantity", request["properties"])
                if field == "replacements":
                    self.assertEqual(sequence["items"], {"$ref": "#/components/schemas/ItemReplacement"})
                else:
                    self.assertEqual(sequence["items"]["type"], "string")

    def test_write_request_fields_are_closed_and_server_computes_amounts(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        address = {"address_line_1", "address_line_2", "city", "region", "country", "postal_code"}
        expected = {
            "/v1/customers/{customer_id}/default-shipping-address": address,
            "/v1/orders/{order_id}/shipping-address": address,
            "/v1/orders/{order_id}/payment-method": {"payment_method_id"},
            "/v1/orders/{order_id}/cancellations": {"reason"},
            "/v1/orders/{order_id}/item-modifications": {"replacements", "payment_method_id"},
            "/v1/orders/{order_id}/returns": {"item_ids", "refund_payment_method_id"},
            "/v1/orders/{order_id}/exchanges": {"replacements", "payment_method_id"},
            "/v1/conversations/{conversation_id}/transfers": {"summary"},
        }
        for path, fields in expected.items():
            with self.subTest(path=path):
                operation = next(iter(spec["paths"][path].values()))
                request = operation["requestBody"]["content"]["application/json"]["schema"]
                self.assertEqual(set(request["properties"]), fields)
                self.assertIs(request["additionalProperties"], False)
                required = address - {"address_line_2"} if fields == address else fields
                self.assertEqual(set(request["required"]), required)

    def test_transfer_receipt_requires_accepted_and_nonempty_id(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        receipt = spec["paths"]["/v1/conversations/{conversation_id}/transfers"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
        self.assertEqual(set(receipt["required"]), {"status", "transfer_id"})
        self.assertEqual(receipt["properties"]["status"]["const"], "accepted")
        self.assertEqual(receipt["properties"]["transfer_id"]["minLength"], 1)
        self.assertIs(receipt["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
