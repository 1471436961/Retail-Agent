"""Original platform entry/module/tool/state compatibility, beyond REST schemas."""
import inspect
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agent"))
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, UserMessage
from tau2.hyper.agent_context import activate_agent_context, build_agent_context
from tau2.utils.llm_utils import validate_message_history
from agent import create_agent
from tools import Tools
from support_agent.application import CustomerAgent
from support_agent.state import SessionState, initial_state
from test_agent import setup_retail, function_call


class InterfaceCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.db,self.requests,self.tools,self.environment=setup_retail()
        self.context=build_agent_context(domain="retail_plus",tools=list(self.tools.get_tools().values()),
                                        resource_root=ROOT/"agent",model_configs=[{"model":"offline/compatibility"}])
        with activate_agent_context(self.context):
            self.agent=create_agent()

    def turn(self,message,state,reply):
        def provider(**kwargs):
            validate_message_history(kwargs["messages"])
            return reply
        with patch("tau2.hyper.agent_context.generate",side_effect=provider) as inference:
            actual,next_state=self.agent.generate_next_message(message,state)
            self.model_request=inference.call_args.kwargs
        return actual,next_state

    def test_original_package_modules_and_factory_signatures_are_restored(self):
        paths=["__init__.py","application.py","state.py","config.py","adapters/__init__.py",
               "adapters/customer_api.py","adapters/customer_tools.py","domain/__init__.py","domain/customer.py"]
        self.assertTrue(all((ROOT/"agent/support_agent"/p).is_file() for p in paths))
        self.assertIs(type(self.agent),CustomerAgent)
        self.assertEqual(str(inspect.signature(create_agent)),"()")
        self.assertEqual(str(inspect.signature(self.agent.get_init_state)),"(message_history=None)")
        self.assertEqual(str(inspect.signature(self.agent.generate_next_message)),"(message, state)")
        self.assertEqual(Tools.__mro__[1].__name__,"CustomerTools")
        self.assertTrue({"turn","pending_call_id","customer_id"} <= set(SessionState.__annotations__))

    def test_original_lookup_tool_signature_and_email_verification_still_work(self):
        signature=inspect.signature(self.tools.lookup_customer)
        self.assertEqual(list(signature.parameters),["customer_id","email"])
        self.assertEqual(signature.parameters["email"].default,"")
        result=self.environment.get_response(function_call("lookup_customer",{"customer_id":"","email":"casey@example.test"}).tool_calls[0])
        self.assertFalse(result.error,result.content)
        self.assertEqual(json.loads(result.content)["customer_id"],"casey")
        self.assertEqual([(r["method"],r["path"]) for r in self.requests],
                         [("POST","/v1/customers/search"),("GET","/v1/customers/casey")])
        self.requests.clear()
        with self.assertRaisesRegex(ValueError,"verification failed"):
            self.tools.lookup_customer("another-person","casey@example.test")
        self.assertEqual(len(self.requests),1)

    def test_json_round_trip_preserves_calls_results_and_original_state_fields(self):
        state=initial_state()
        self.assertEqual({k:state[k] for k in ("turn","pending_call_id","customer_id")},
                         {"turn":0,"pending_call_id":None,"customer_id":None})
        call=function_call("lookup_customer",{"customer_id":"","email":"casey@example.test"},"original-lookup")
        _,state=self.turn(UserMessage(role="user",content="Please use casey@example.test"),state,call)
        state=json.loads(json.dumps(state,allow_nan=False))
        self.assertEqual(state["pending_call_id"],"original-lookup")
        result=self.environment.get_response(call.tool_calls[0])
        _,state=self.turn(MultiToolMessage(role="tool",tool_messages=[result]),state,
                          AssistantMessage(role="assistant",content="What can I help with?"))
        json.dumps(state,allow_nan=False)
        self.assertEqual(state["turn"],2)
        self.assertIsNone(state["pending_call_id"])
        self.assertEqual(self.model_request["messages"][-1].id,"original-lookup")
        self.assertEqual(json.loads(self.model_request["messages"][-1].content)["customer_id"],"casey")

    def test_legacy_three_field_state_accepts_a_new_user_turn(self):
        legacy={"turn":7,"pending_call_id":None,"customer_id":"casey"}
        reply,state=self.turn(UserMessage(role="user",content="Can you help me?"),legacy,
                              AssistantMessage(role="assistant",content="Yes. What do you need?"))
        self.assertEqual(state["turn"],8)
        self.assertEqual(state["customer_id"],"casey")
        self.assertEqual(legacy,{"turn":7,"pending_call_id":None,"customer_id":"casey"})
        self.assertEqual(self.model_request["messages"][-1].content,"Can you help me?")

    def test_native_tool_batch_and_all_results_survive_json_serialization(self):
        batch=AssistantMessage(role="assistant",tool_calls=[
            ToolCall(id="product",name="get_product_details",arguments={"product_id":"shirt"}),
            ToolCall(id="item",name="get_item_details",arguments={"item_id":"new"})])
        actual,state=self.turn(UserMessage(role="user",content="Please inspect the catalog options."),initial_state(),batch)
        self.assertEqual([c.id for c in actual.tool_calls],["product","item"])
        state=json.loads(json.dumps(state,allow_nan=False))
        results=[self.environment.get_response(c) for c in actual.tool_calls]
        self.assertTrue(all(not r.error for r in results))
        reply,state=self.turn(MultiToolMessage(role="tool",tool_messages=results),state,
                              AssistantMessage(role="assistant",content="The red variant is available."))
        self.assertEqual([m.id for m in self.model_request["messages"][-2:]],["product","item"])
        self.assertEqual(json.loads(self.model_request["messages"][-1].content)["available"],True)
        json.dumps(state,allow_nan=False)


if __name__=="__main__":
    unittest.main()
