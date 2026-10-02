"""Error and replay-related transport rules from the published OpenAPI."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.adapters.client_api import ClientAPIError, HTTP_KINDS, request_object
from support_agent.adapters.customer_api import verify_and_read_customer
from fakes import FakeClientAPI


class ClientAPIContractTests(unittest.TestCase):
    def test_transfer_success_requires_explicit_201(self):
        api = SimpleNamespace(request=Mock(return_value=SimpleNamespace(status_code=201, body={"status": "accepted", "transfer_id": "synthetic"})))
        result = request_object(api, "POST", "/v1/conversations/test/transfers", body={"summary": "test"}, expected_status=201, mutates=True)
        self.assertEqual(result["status"], "accepted")
        with self.assertRaises(ClientAPIError) as caught:
            request_object(api, "POST", "/v1/conversations/test/transfers", body={"summary": "test"}, mutates=True)
        self.assertEqual(caught.exception.kind, "unexpected_status")
        self.assertTrue(caught.exception.outcome_unknown)

    def test_statuses_keep_public_error_codes(self):
        spec_path = Path(__file__).resolve().parents[1] / "materials" / "client_api" / "openapi.yaml"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        documented_errors = {int(code) for methods in spec["paths"].values() for method, operation in methods.items() if method in {"get", "post", "put"} for code in operation["responses"] if int(code) >= 400}
        self.assertEqual(set(HTTP_KINDS), documented_errors)
        for status, kind in HTTP_KINDS.items():
            with self.subTest(status=status):
                response = SimpleNamespace(status_code=status, body={"error": {"code": "sample_code", "message": "A detail"}})
                api = SimpleNamespace(request=Mock(return_value=response))
                with self.assertRaises(ClientAPIError) as caught:
                    request_object(api, "GET", "/v1/orders/%23TEST1")
                self.assertEqual((caught.exception.kind, caught.exception.status_code, caught.exception.code), (kind, status, "sample_code"))
                self.assertFalse(caught.exception.outcome_unknown)
                api.request.assert_called_once()

    def test_transport_after_write_is_unknown_and_never_retried(self):
        api = FakeClientAPI(fail_after_write=True)
        address = {"address_line_1": "2 Test St", "city": "Testville", "region": "CA", "country": "US", "postal_code": "90002"}
        with self.assertRaises(ClientAPIError) as caught:
            request_object(api, "PUT", "/v1/customers/customer_a/default-shipping-address", body=address, mutates=True)
        self.assertEqual(caught.exception.kind, "transport")
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.customers["customer_a"]["default_shipping_address"], address)

    def test_read_transport_failure_is_classified_without_side_effect(self):
        api = SimpleNamespace(request=Mock(side_effect=TimeoutError("offline")))
        with self.assertRaises(ClientAPIError) as caught:
            request_object(api, "GET", "/v1/orders/%23TEST1")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(caught.exception.kind, "transport")
        api.request.assert_called_once()

    def test_invalid_success_body_is_not_treated_as_record(self):
        api = SimpleNamespace(request=Mock(return_value=SimpleNamespace(status_code=200, body=[])))
        with self.assertRaises(ClientAPIError) as caught:
            request_object(api, "GET", "/v1/customers/customer_a")
        self.assertEqual(caught.exception.kind, "invalid_response")
        with self.assertRaises(ClientAPIError) as write_error:
            request_object(api, "PUT", "/v1/customers/customer_a/default-shipping-address", body={}, mutates=True)
        self.assertTrue(write_error.exception.outcome_unknown)
        self.assertEqual(api.request.call_count, 2)

    def test_write_502_is_uncertain_but_business_409_is_definite(self):
        for status, unknown in ((502, True), (409, False)):
            with self.subTest(status=status):
                response = SimpleNamespace(status_code=status, body={"error": {"code": "sample", "message": "details"}})
                api = SimpleNamespace(request=Mock(return_value=response))
                with self.assertRaises(ClientAPIError) as caught:
                    request_object(api, "PUT", "/v1/orders/%23TEST1/payment-method", body={"payment_method_id": "card_a"}, mutates=True)
                self.assertEqual(caught.exception.outcome_unknown, unknown)
                api.request.assert_called_once()

    def test_write_without_integer_status_is_unknown_even_with_checker(self):
        for status in (None, True, "200", 200.0):
            with self.subTest(status=status):
                checker = Mock()
                response = SimpleNamespace(body={"updated": True}, raise_for_status=checker)
                if status is not None:
                    response.status_code = status
                api = SimpleNamespace(request=Mock(return_value=response))
                with self.assertRaises(ClientAPIError) as caught:
                    request_object(api, "PUT", "/v1/orders/%23TEST1/payment-method",
                                   body={"payment_method_id": "card_a"}, mutates=True)
                self.assertEqual(caught.exception.kind, "invalid_response")
                self.assertTrue(caught.exception.outcome_unknown)
                api.request.assert_called_once()
                checker.assert_not_called()

    def test_noninteger_read_status_is_rejected_not_coerced(self):
        for status in (True, "200", 200.0):
            with self.subTest(status=status):
                api = SimpleNamespace(request=Mock(return_value=SimpleNamespace(
                    status_code=status, body={"customer_id": "customer_a"}, raise_for_status=Mock())))
                with self.assertRaises(ClientAPIError) as caught:
                    request_object(api, "GET", "/v1/customers/customer_a")
                self.assertEqual(caught.exception.kind, "invalid_response")
                self.assertFalse(caught.exception.outcome_unknown)
                api.request.assert_called_once()

    def test_lookup_rejects_details_that_do_not_match_search(self):
        api = SimpleNamespace(request=Mock(side_effect=[
            SimpleNamespace(status_code=200, body={"customer_id": "customer_a"}),
            SimpleNamespace(status_code=200, body={"customer_id": "customer_a", "email": "other@example.test"}),
        ]))
        with self.assertRaisesRegex(ValueError, "verification failed"):
            verify_and_read_customer(api, "customer_a", "a@example.test")
        self.assertEqual(api.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
