"""Ownership, identity and six read endpoint boundaries using synthetic records."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.adapters import read_api
from support_agent.adapters.customer_api import verify_and_read_customer
from support_agent.domain.identity import proof_from_text, verification_inputs
from m2_fakes import ReadFake
from fakes import FakeResponse

PROOF = {"customer_id": "customer_a", "email": "a@example.test"}


class ReadEndpointTests(unittest.TestCase):
    def test_duplicate_product_and_variant_ids_are_rejected_at_read_boundary(self):
        for kind in ("product", "variant"):
            api = ReadFake()
            if kind == "product":
                api.products["duplicate-key"] = deepcopy(api.products["product_mug"])
                read = lambda: read_api.list_products(api, **PROOF)
                endpoint = "/v1/catalog/products"
            else:
                api.products["product_mug"]["items"].append(deepcopy(api.products["product_mug"]["items"][0]))
                read = lambda: read_api.get_product(api, "product_mug", **PROOF)
                endpoint = "/v1/catalog/products/product_mug"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Repeated"):
                read()
            self.assertEqual([p for _, p, _ in api.calls], ["/v1/customers/search", "/v1/customers/customer_a", endpoint])

    def test_legacy_lookup_requires_the_same_explicit_profile_identity(self):
        for profile in ({"email": "a@example.test"}, {"customer_id": "customer_b", "email": "a@example.test"}):
            api = Mock()
            api.request.side_effect = [FakeResponse(200, {"customer_id": "customer_a"}), FakeResponse(200, profile)]
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                verify_and_read_customer(api, "customer_a", "a@example.test")
        api = ReadFake()
        self.assertEqual(verify_and_read_customer(api, "customer_a", " A@EXAMPLE.TEST ")["customer_id"], "customer_a")
        for email in ("", "not-an-email", True):
            api = Mock()
            with self.subTest(email=email), self.assertRaises(ValueError):
                verify_and_read_customer(api, "customer_a", email)
            api.request.assert_not_called()

    def test_bad_order_amount_payment_or_fulfillment_is_rejected(self):
        for problem in ("price", "payment", "fulfillment"):
            api = ReadFake()
            order = api.orders["#TEST1"]
            if problem == "price":
                order["items"][0]["price"] = True
            elif problem == "payment":
                order["payments"] = [{"transaction_type":"refund", "amount":"12.50", "payment_method_id":"card_a"}]
            else:
                order["fulfillments"] = [{"item_ids":["item_blue"],"tracking_id":"TRACK"}]
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                read_api.get_order(api, "#TEST1", **PROOF)

    def test_email_and_name_postal_search_precede_profile_details(self):
        for proof in (PROOF, {"customer_id": "customer_a", "first_name": "Alice", "last_name": "Example", "postal_code": "10001"}):
            with self.subTest(proof=proof):
                api = ReadFake()
                result = read_api.verify_customer(api, **proof)
                self.assertEqual(result["customer_id"], "customer_a")
                self.assertEqual([r[:2] for r in api.calls], [("POST", "/v1/customers/search"), ("GET", "/v1/customers/customer_a")])

    def test_partial_mixed_or_boolean_verification_has_zero_requests(self):
        for args in ({}, {"customer_id": "customer_a"}, {"first_name": "Alice", "last_name": "Example"},
                     {"email": "a@example.test", "postal_code": "10001"}, {"postal_code": True}):
            api = ReadFake()
            with self.subTest(args=args), self.assertRaises(ValueError):
                read_api.verify_customer(api, **args)
            self.assertFalse(api.calls)

    def test_search_mismatch_and_failed_search_do_not_read_profile(self):
        for args in ({"customer_id": "customer_b", "email": "a@example.test"}, {"email": "missing@example.test"}):
            api = ReadFake()
            with self.subTest(args=args), self.assertRaises(ValueError):
                read_api.verify_customer(api, **args)
            self.assertEqual(len(api.calls), 1)

    def test_mismatched_name_or_postal_in_detail_is_rejected(self):
        api = ReadFake()
        bad = deepcopy(api.customers["customer_a"])
        for field in ("first_name", "last_name", "postal_code"):
            response = deepcopy(bad)
            (response["name"] if field != "postal_code" else response["default_shipping_address"])[field] = "different"
            client = Mock()
            client.request.side_effect = [FakeResponse(200, {"customer_id": "customer_a"}), FakeResponse(200, response)]
            with self.subTest(field=field), self.assertRaises(ValueError):
                read_api.verify_customer(client, first_name="Alice", last_name="Example", postal_code="10001")

    def test_six_read_paths_and_encoded_order_id_are_used_without_writes(self):
        api = ReadFake()
        read_api.verify_customer(api, **PROOF)
        order = read_api.get_order(api, "#TEST1", **PROOF)
        products = read_api.list_products(api, **PROOF)
        product = read_api.get_product(api, "product_mug", **PROOF)
        item = read_api.get_item(api, "item_blue", **PROOF)
        self.assertEqual(order["items"][0]["price"], 12.5)
        self.assertEqual(len(products["products"]), 1)
        self.assertEqual(len(product["items"]), 1)
        self.assertTrue(item["available"])
        paths = {p for _, p, _ in api.calls}
        self.assertEqual(paths, {"/v1/customers/search", "/v1/customers/customer_a", "/v1/orders/%23TEST1", "/v1/catalog/products", "/v1/catalog/products/product_mug", "/v1/catalog/items/item_blue"})
        self.assertTrue(all(m == "GET" or (m, p) == ("POST", "/v1/customers/search") for m, p, _ in api.calls))

    def test_roommate_order_is_rejected_before_order_get(self):
        api = ReadFake()
        with self.assertRaises(ValueError):
            read_api.get_order(api, "#TEST2", **PROOF)
        self.assertFalse(any(p.startswith("/v1/orders/") for _, p, _ in api.calls))

    def test_owned_reference_with_wrong_returned_owner_or_id_is_rejected(self):
        for field, value in (("customer_id", "customer_b"), ("order_id", "#TEST2")):
            api = ReadFake()
            api.orders["#TEST1"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                read_api.get_order(api, "#TEST1", **PROOF)

    def test_exact_status_filter_keeps_modified_pending_distinct(self):
        api = ReadFake()
        other = deepcopy(api.orders["#TEST1"])
        other.update(order_id="#MODIFIED", status="pending (items modified)")
        api.orders["#MODIFIED"] = other
        api.customers["customer_a"]["order_ids"].append("#MODIFIED")
        result = read_api.list_customer_orders(api, status="pending", **PROOF)
        self.assertEqual([o["order_id"] for o in result["orders"]], ["#TEST1"])
        api.calls.clear()
        with self.assertRaises(ValueError):
            read_api.list_customer_orders(api, status="shipped", **PROOF)
        self.assertFalse(api.calls)

    def test_unknown_state_and_oversized_order_lists_fail_without_partial_report(self):
        api = ReadFake()
        api.orders["#TEST1"]["status"] = "shipped"
        with self.assertRaises(ValueError):
            read_api.list_customer_orders(api, **PROOF)
        api = ReadFake()
        api.customers["customer_a"]["order_ids"] = [f"#{i}" for i in range(33)]
        with self.assertRaises(ValueError):
            read_api.list_customer_orders(api, **PROOF)
        self.assertFalse(any(p.startswith("/v1/orders/") for _, p, _ in api.calls))

    def test_catalog_is_public_but_still_requires_verification(self):
        api = ReadFake()
        api.products["product_unowned"] = {"product_id": "product_unowned", "name": "Public example", "items": []}
        result = read_api.get_product(api, "product_unowned", **PROOF)
        self.assertEqual(result["product_id"], "product_unowned")
        api.calls.clear()
        with self.assertRaises(ValueError):
            read_api.list_products(api, customer_id="customer_a")
        self.assertFalse(api.calls)

    def test_bad_catalog_id_availability_or_price_is_not_a_fact(self):
        for field, value in (("item_id", "wrong"), ("available", "true"), ("price", True), ("price", float("nan")), ("price", "12.50")):
            api = ReadFake()
            api.products["product_mug"]["items"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                read_api.get_item(api, "item_blue", **PROOF)

    def test_explicit_verification_text_preserves_string_postal_codes(self):
        proof = proof_from_text("first_name: Alice; last_name: Example; postal_code: 01001")
        self.assertEqual(proof["postal_code"], "01001")
        self.assertIsNone(proof_from_text("first_name: Alice; last_name: Example"))
        self.assertEqual(verification_inputs(email="A@example.test")["email"], "A@example.test")
