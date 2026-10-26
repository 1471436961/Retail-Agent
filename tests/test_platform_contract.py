"""All tool endpoints are constrained by the original classroom OpenAPI."""
import sys
from pathlib import Path
import unittest

from jsonschema import ValidationError
from tau2.hyper.client_api import ClientAPI, ClientAPIContext

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agent"))
from tools import Tools
from platform_contract import CONTRACT, validate_request, validate_response


class PlatformContractTests(unittest.TestCase):
    def test_all_documented_endpoints_are_reachable_with_platform_request_schemas(self):
        observed=set()
        def record(request):
            path=validate_request(request)
            observed.add((request["method"].lower(),path))
            return {"status_code":200,"body":{},"headers":{}}
        toolkit=Tools(ClientAPI(record,context=ClientAPIContext(conversation_id="test/conversation")))
        address=dict(address1="12 Test Road",address2="",city="Test City",state="CA",country="USA",zip="90210")
        toolkit.find_user_id_by_email("test@example.test")
        toolkit.find_user_id_by_name_zip("Test","User","90210")
        toolkit.get_user_details("customer")
        toolkit.get_order_details("#P1")
        toolkit.list_all_product_types()
        toolkit.get_product_details("product")
        toolkit.get_item_details("item")
        toolkit.modify_user_address(user_id="customer",**address)
        toolkit.modify_pending_order_address(order_id="#P1",**address)
        toolkit.modify_pending_order_payment("#P1","paypal_test")
        toolkit.cancel_pending_order("#P1","no longer needed")
        toolkit.modify_pending_order_items("#P1",["old"],["new"],"paypal_test")
        toolkit.exchange_delivered_order_items("#D1",["old"],["new"],"paypal_test")
        toolkit.return_delivered_order_items("#D1",["old"],"paypal_test")
        toolkit.transfer_to_human_agents("Customer requested help")
        expected={(method,path) for path,methods in CONTRACT["paths"].items()
                  for method in methods if method in {"get","put","post","patch","delete"}}
        self.assertEqual(observed,expected)
        self.assertEqual(len(observed),14)

    def test_upstream_field_names_do_not_silently_pass_as_platform_payloads(self):
        wrong=[{"method":"POST","path":"/v1/customers/search","body":{"first_name":"Test","last_name":"User","zip":"90210"}},
               {"method":"POST","path":"/v1/orders/%23D1/returns","body":{"item_ids":["old"],"payment_method_id":"paypal_test"}},
               {"method":"POST","path":"/v1/orders/%23D1/exchanges","body":{"item_ids":["old"],"new_item_ids":["new"],"payment_method_id":"paypal_test"}}]
        for request in wrong:
            with self.subTest(path=request["path"]),self.assertRaises(ValidationError):
                validate_request(request)

    def test_stringified_scalar_is_rejected_by_original_response_schema(self):
        request={"method":"GET","path":"/v1/catalog/items/item"}
        response={"status_code":200,"body":{"item_id":"item","options":{},"available":"true","price":12.5}}
        with self.assertRaises(ValidationError):
            validate_response(request,response)


if __name__=="__main__":
    unittest.main()
