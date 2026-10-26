"""Focused integration checks: real SDK/gateway, synthetic retail data, no network."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


def deny_network(event, arguments):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("Offline tests forbid network access")


sys.addaudithook(deny_network)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from loguru import logger
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, UserMessage
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools
from tau2.environment.environment import Environment
from tau2.hyper.agent_context import activate_agent_context, build_agent_context
from tau2.hyper.client_api import ClientAPI
from tau2.hyper.client_api.runtime import ClientAPIRuntime
from tau2.utils.llm_utils import to_litellm_messages, validate_message_history
from agent import create_agent
from tools import Tools

logger.disable("tau2.environment.environment")


def setup_retail():
    """Only invented development records, never task/evaluation fixtures."""
    address = dict(address1="10 Sample Road", address2="", city="Sample City",
                   state="CA", country="USA", zip="90210")
    old = dict(item_id="old", options={"color": "blue", "size": "M"}, available=True, price=20.0)
    new = dict(item_id="new", options={"color": "red", "size": "M"}, available=True, price=23.5)
    item = dict(name="Test shirt", product_id="shirt", **{k:v for k,v in old.items() if k != "available"})
    orders = {identifier:dict(order_id=identifier, user_id="casey", address=address,
                             items=[item], status=status, fulfillments=[],
                             payment_history=[dict(transaction_type="payment", amount=20,
                                                   payment_method_id="paypal_test")])
              for identifier,status in (("#P1","pending"),("#D1","delivered"))}
    db = RetailDB.model_validate(dict(users={"casey":dict(user_id="casey", name=dict(first_name="Casey",last_name="Morgan"),
                  email="casey@example.test", address=address, orders=list(orders),
                  payment_methods={"paypal_test":dict(source="paypal",id="paypal_test"),
                                   "gift_test":dict(source="gift_card",id="gift_test",balance=100.0)})},
                  products={"shirt":dict(name="Test shirt",product_id="shirt",variants={"old":old,"new":new})},
                  orders=orders))
    runtime = ClientAPIRuntime(Environment("retail_plus", "", RetailTools(db)), conversation_id="offline/conversation")
    requests = []

    def transport(payload):
        requests.append(payload)
        return runtime.dispatch(payload)

    toolkit = Tools(ClientAPI(transport, context=runtime.context))
    return db, requests, toolkit, Environment("retail_plus", "", toolkit)


def function_call(name, arguments, identifier="call-1"):
    return AssistantMessage(role="assistant", tool_calls=[ToolCall(id=identifier,name=name,arguments=arguments)])


class NativeAgentTests(unittest.TestCase):
    def setUp(self):
        self.db, self.requests, self.tools, self.environment = setup_retail()
        self.context = build_agent_context(domain="retail_plus", tools=list(self.tools.get_tools().values()),
                     resource_root=ROOT/"agent", model_configs=[{"model":"offline/teacher-model",
                     "constraints":{"max_tokens":777,"temperature":{"one_of":[0,0.4]}}}])
        with activate_agent_context(self.context):
            self.agent = create_agent()

    def run_model(self, message, state, result):
        # Patch below ModelGateway.generate, not the gateway itself: real
        # configuration validation/injection and model credit hooks still run.
        def provider(**kwargs):
            validate_message_history(kwargs["messages"])
            self.provider_request = kwargs
            return result
        with patch("tau2.hyper.agent_context.generate", side_effect=provider):
            return self.agent.generate_next_message(message, state)

    def test_plain_customer_language_and_plain_model_reply_need_no_candidate_json(self):
        original="I received a keyboard and thermostat. Can you help me exchange both?"
        reply=AssistantMessage(role="assistant",content="Of course. What is your email or name and postal code?")
        actual,state=self.run_model(UserMessage(role="user",content=original),self.agent.get_init_state(),reply)
        self.assertIs(actual,reply)
        self.assertEqual(state["messages"][0].content,original)
        self.assertEqual(len(self.provider_request["tools"]),16)
        self.assertEqual(self.provider_request["model"],"offline/teacher-model")
        self.assertEqual(self.provider_request["max_tokens"],777)
        self.assertEqual(self.provider_request["temperature"],0)

    def test_native_name_lookup_tool_result_is_fed_back_to_the_model(self):
        user=UserMessage(role="user",content="I'm Casey Morgan; my ZIP is 90210. I can't remember my email.")
        call=function_call("find_user_id_by_name_zip",dict(first_name="Casey",last_name="Morgan",zip="90210"))
        actual,state=self.run_model(user,self.agent.get_init_state(),call)
        outcome=self.environment.get_response(actual.tool_calls[0])
        self.assertFalse(outcome.error)
        self.assertEqual(json.loads(outcome.content),{"customer_id":"casey"})
        reply=AssistantMessage(role="assistant",content="Thank you. I found your account.")
        _,state=self.run_model(MultiToolMessage(role="tool",tool_messages=[outcome]),state,reply)
        wire=to_litellm_messages(self.provider_request["messages"])
        self.assertEqual(wire[-1]["tool_call_id"],"call-1")
        self.assertEqual(json.loads(wire[-1]["content"])["customer_id"],"casey")
        self.assertEqual(len(self.requests),1)

    def test_original_correction_and_condition_are_sent_unchanged(self):
        state=self.agent.get_init_state([UserMessage(role="user",content="Change it to red."),
               AssistantMessage(role="assistant",content="Red, same size. Shall I proceed?")])
        text="Actually keep blue; go ahead only if it is cheaper."
        reply=AssistantMessage(role="assistant",content="I'll check the blue options and price first.")
        _,next_state=self.run_model(UserMessage(role="user",content=text),state,reply)
        self.assertEqual(self.provider_request["messages"][-1].content,text)
        self.assertEqual(len(state["messages"]),2)
        self.assertEqual(len(next_state["messages"]),4)
        self.assertFalse(self.requests)

    def test_snapshot_history_restores_without_replaying_tools(self):
        user=UserMessage(role="user",content="casey@example.test")
        call=function_call("find_user_id_by_email",{"email":"casey@example.test"})
        _,state=self.run_model(user,self.agent.get_init_state(),call)
        outcome=self.environment.get_response(call.tool_calls[0])
        restored=self.agent.get_init_state([*state["messages"],MultiToolMessage(role="tool",tool_messages=[outcome])])
        self.assertEqual(len(self.requests),1)
        self.assertEqual(restored["messages"][-1].id,"call-1")
        self.assertEqual(restored["messages"][-1].content,outcome.content)

    def test_gateway_exception_is_observable_and_is_not_a_fake_business_reply(self):
        with patch("tau2.hyper.agent_context.generate",side_effect=RuntimeError("offline provider failure")):
            with self.assertRaisesRegex(RuntimeError,"offline provider failure"):
                self.agent.generate_next_message(UserMessage(role="user",content="Please help"),self.agent.get_init_state())
        self.assertFalse(self.requests)

    def test_tool_preamble_does_not_become_a_customer_success_claim(self):
        call=function_call("get_order_details",{"order_id":"#P1"})
        call.content="I'll inspect it."
        reply,state=self.run_model(UserMessage(role="user",content="Check my order"),self.agent.get_init_state(),call)
        self.assertIsNone(reply.content)
        self.assertEqual(reply.tool_calls[0].name,"get_order_details")

    def test_real_candidate_broker_serializes_full_tool_schemas_and_history(self):
        import io
        from types import SimpleNamespace
        from tau2.hyper.sandbox.candidate_server import _brokered_generate
        result=AssistantMessage(role="assistant",content="What is your email address?")
        inbound=io.StringIO(json.dumps({"id":"fixed-id","ok":True,"result":result.model_dump(mode="json")})+"\n")
        outbound=io.StringIO()
        with patch("tau2.hyper.agent_context.generate",side_effect=_brokered_generate),\
             patch("tau2.hyper.sandbox.candidate_server.uuid.uuid4",return_value=SimpleNamespace(hex="fixed-id")),\
             patch("sys.stdin",inbound),patch("sys.stdout",outbound):
            reply,state=self.agent.generate_next_message(UserMessage(role="user",content="Could we exchange my shirt?"),self.agent.get_init_state())
        payload=json.loads(outbound.getvalue().removeprefix("__TAU2_MODEL_REQUEST__"))
        self.assertEqual(reply.content,result.content)
        self.assertEqual(len(payload["tools"]),16)
        self.assertEqual(payload["kwargs"]["max_tokens"],777)
        self.assertEqual(payload["messages"][-1]["content"],"Could we exchange my shirt?")
        self.assertIn("exchange_delivered_order_items",{s["function"]["name"] for s in payload["tools"]})

    def test_model_selected_exchange_changes_the_real_reference_backend(self):
        state=self.agent.get_init_state()
        greeting=AssistantMessage(role="assistant",content="I can help. What is your name and postal code?")
        _,state=self.run_model(UserMessage(role="user",content="I received my blue shirt. I'd like red, keeping the size."),state,greeting)
        lookup=function_call("find_user_id_by_name_zip",dict(first_name="Casey",last_name="Morgan",zip="90210"),"identity")
        reply,state=self.run_model(UserMessage(role="user",content="Casey Morgan, 90210."),state,lookup)
        next_calls=[("get_user_details",{"user_id":"casey"}),
                    ("get_order_details",{"order_id":"#D1"}),
                    ("get_product_details",{"product_id":"shirt"})]
        for n,(name,args) in enumerate(next_calls):
            outcome=self.environment.get_response(reply.tool_calls[0])
            self.assertFalse(outcome.error,outcome.content)
            reply,state=self.run_model(MultiToolMessage(role="tool",tool_messages=[outcome]),state,
                                        function_call(name,args,"inspect-"+str(n)))
        catalog=self.environment.get_response(reply.tool_calls[0])
        recap=AssistantMessage(role="assistant",content="For #D1: exchange all one blue M shirt for red M, +$3.50 via PayPal. Is that everything, and may I proceed?")
        _,state=self.run_model(MultiToolMessage(role="tool",tool_messages=[catalog]),state,recap)
        self.assertEqual(self.db.orders["#D1"].status,"delivered")
        user=UserMessage(role="user",content="Yes, that's everything. Please go ahead using PayPal.")
        call=function_call("exchange_delivered_order_items",dict(order_id="#D1",item_ids=["old"],new_item_ids=["new"],payment_method_id="paypal_test"))
        reply,state=self.run_model(user,state,call)
        result=self.environment.get_response(reply.tool_calls[0])
        self.assertFalse(result.error,result.content)
        receipt=json.loads(result.content)
        self.assertEqual(receipt["status"],"exchange requested")
        self.assertEqual(receipt["exchange"]["price_difference"],3.5)
        self.assertEqual(self.db.orders["#D1"].status,"exchange requested")
        response=AssistantMessage(role="assistant",content="Your exchange was requested. This does not confirm shipment.")
        actual,_=self.run_model(MultiToolMessage(role="tool",tool_messages=[result]),state,response)
        self.assertIs(actual,response)


class RetailToolTests(unittest.TestCase):
    def setUp(self):
        self.db,self.requests,self.tools,self.environment=setup_retail()

    def test_sdk_discovers_only_our_toolkit_and_no_internal_state_parameters(self):
        import tools
        from tau2.hyper.client_api import ClientAPIToolKitBase
        from tau2.hyper.sandbox.candidate_server import _find_subclass
        self.assertIs(_find_subclass(tools,ClientAPIToolKitBase),Tools)
        self.assertEqual(len(self.tools.get_tools()),16)
        self.assertFalse(any("session_json" in t.params.model_fields for t in self.tools.get_tools().values()))

    def test_read_operations_and_json_scalars_use_the_real_sdk_transport(self):
        cases=[("find_user_id_by_email",{"email":"casey@example.test"}),
               ("get_user_details",{"user_id":"casey"}),("get_order_details",{"order_id":"#P1"}),
               ("list_all_product_types",{}),("get_product_details",{"product_id":"shirt"}),
               ("get_item_details",{"item_id":"new"})]
        for name,args in cases:
            with self.subTest(name=name):
                result=self.environment.get_response(function_call(name,args).tool_calls[0])
                self.assertFalse(result.error,result.content)
                body=json.loads(result.content)
                self.assertIsInstance(body,dict)
                if name=="get_item_details":
                    self.assertIs(type(body["available"]),bool)
                    self.assertIsInstance(body["price"],(float,int))
        self.assertIn("%23P1",self.requests[2]["path"])

    def test_address_and_payment_updates_reach_correct_rest_endpoints(self):
        args=dict(address1="25 New Road",address2="",city="New City",state="NY",country="USA",zip="10001")
        self.tools.modify_user_address(user_id="casey",**args)
        self.tools.modify_pending_order_address(order_id="#P1",**args)
        self.tools.modify_pending_order_payment("#P1","gift_test")
        self.assertEqual(self.db.users["casey"].address.address1,"25 New Road")
        self.assertEqual(self.db.orders["#P1"].address.zip,"10001")
        new_payments=[p for p in self.db.orders["#P1"].payment_history
                      if p.transaction_type=="payment" and p.payment_method_id=="gift_test"]
        self.assertEqual(len(new_payments),1)
        self.assertEqual(new_payments[0].amount,20.0)

    def test_pending_item_change_is_one_complete_submission(self):
        body=self.tools.modify_pending_order_items("#P1",["old"],["new"],"paypal_test")
        self.assertEqual(body["status"],"pending (items modified)")
        self.assertEqual(self.db.orders["#P1"].items[0].item_id,"new")
        self.assertEqual(self.requests[-1]["body"]["replacements"],[{"existing_item_id":"old","replacement_item_id":"new"}])

    def test_return_and_cancellation_use_original_platform_business_rules(self):
        cancelled=self.tools.cancel_pending_order("#P1","no longer needed")
        returned=self.tools.return_delivered_order_items("#D1",["old"],"paypal_test")
        self.assertEqual(cancelled["status"],"cancelled")
        self.assertEqual(returned["status"],"return requested")
        self.assertEqual(self.db.orders["#P1"].status,"cancelled")
        self.assertEqual(self.db.orders["#D1"].return_items,["old"])

    def test_invalid_pair_lengths_fail_before_any_request(self):
        with self.assertRaises(ValueError):
            self.tools.exchange_delivered_order_items("#D1",["old"],[],"paypal_test")
        self.assertFalse(self.requests)

    def test_backend_rejection_is_a_tool_error_not_a_fabricated_success(self):
        result=self.environment.get_response(function_call("cancel_pending_order",dict(order_id="#D1",reason="no longer needed")).tool_calls[0])
        self.assertTrue(result.error)
        self.assertEqual(self.db.orders["#D1"].status,"delivered")
        self.assertEqual(len(self.requests),1)

    def test_transport_failure_does_not_retry_a_mutation(self):
        def broken(payload):
            raise TimeoutError("Synthetic lost write response")
        toolkit=Tools(ClientAPI(broken))
        with patch.object(toolkit.client_api,"_transport",side_effect=broken) as transport:
            with self.assertRaises(TimeoutError):
                toolkit.cancel_pending_order("#P1","no longer needed")
            self.assertEqual(transport.call_count,1)

    def test_transfer_uses_only_platform_conversation_context(self):
        result=self.tools.transfer_to_human_agents("Customer requests a supervisor.")
        self.assertEqual(result["status"],"accepted")
        self.assertEqual(self.requests[-1]["path"],"/v1/conversations/offline%2Fconversation/transfers")

    def test_calculator_rejects_code_names_calls_and_nonfinite_values(self):
        self.assertEqual(self.tools.calculate("(23.5 - 20) * 2"),"7.0")
        for expression in ("__import__('os')", "1e999", "(1).__class__", "2 ** 100", "True + 1"):
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                self.tools.calculate(expression)


if __name__ == "__main__":
    unittest.main()
