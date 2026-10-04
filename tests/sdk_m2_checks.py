"""Isolated real-SDK contract checks; rejects sockets before importing tau2."""
import sys
from pathlib import Path

network_attempts = []
def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        network_attempts.append(event)
        raise RuntimeError("Network is forbidden in offline SDK checks")
sys.addaudithook(audit)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import json
from types import SimpleNamespace
import unittest

from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage, UserMessage
from tau2.hyper.client_api import ClientAPI, ClientAPIContext
from support_agent.adapters.customer_tools import CustomerTools
from support_agent.adapters.model_gateway import ModelAdapter, ModelGatewayFailure, sdk_messages, usage_record
from support_agent.application import CustomerAgent
from support_agent.protocol import InvalidAction, ToolOutcome, TurnInput
from support_agent.read_session import advance, bind_arguments
from support_agent.state import initial_state
from test_m2_session import verified_state
from m2_fakes import ReadFake


class Interface:
    def __init__(self, tools):
        self.available = tuple(tools.values())
    def select(self, names):
        return tuple(t for t in self.available if t.name in names)


class Gateway:
    available_models = ("offline/read-model",)
    models = (SimpleNamespace(model="offline/read-model", constrained_args={"max_tokens": 1024}),)
    def __init__(self, response=None, failure=None):
        self.response, self.failure, self.calls = response, failure, []
    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.response


def context(gateway=None):
    toolkit = CustomerTools(ReadFake())
    return SimpleNamespace(model_gateway=gateway or Gateway(), action_interface=Interface(toolkit.get_tools()))


class RealSDKChecks(unittest.TestCase):
    def test_real_agent_profile_tool_reads_and_formats_the_verified_customer(self):
        backend, state = verified_state()
        agent = CustomerAgent()
        outgoing, waiting = agent.generate_next_message(UserMessage(role="user", content="Show my profile"), state)
        self.assertEqual(outgoing.tool_calls[0].name, "read_customer_profile")
        backend.calls.clear()
        call = outgoing.tool_calls[0]
        body = CustomerTools(backend).read_customer_profile(**call.arguments)
        self.assertEqual([p for _,p,_ in backend.calls], ["/v1/customers/search", "/v1/customers/customer_a"])
        reply, done = agent.generate_next_message(MultiToolMessage(role="tool", tool_messages=[ToolMessage(role="tool", id=call.id, content=json.dumps(body), error=False)]), waiting)
        self.assertIsInstance(reply, AssistantMessage)
        self.assertFalse(reply.tool_calls)
        self.assertEqual(json.loads(reply.content.split(": ",1)[1])["customer_id"], "customer_a")
        self.assertEqual(done["identity"], state["identity"])
        self.assertEqual(done["customer_record"], body)
        self.assertFalse(done["pending_calls"])
        self.assertEqual(done, json.loads(json.dumps(done)))

    def test_rejected_legacy_history_is_not_replayed_as_model_facts(self):
        from copy import deepcopy
        _, state = verified_state()
        call, waiting = advance(TurnInput(kind="user",content="order #TEST1"),state)
        for content,error in (("private-provider-error-marker",True),
                (json.dumps({"customer_id":"customer_b","order_id":"#TEST1","note":"private-foreign-owner-marker"}),False)):
            with self.subTest(error=error):
                _, done = advance(TurnInput(kind="tools",outcomes=(ToolOutcome(id=call.calls[0].id,content=content,error=error),)),waiting)
                # Simulate an already-persisted state from before sanitization.
                legacy = deepcopy(done)
                legacy["history"][-2]["content"] = content
                legacy["history"][-2]["error"] = error
                snapshot = json.dumps(legacy,sort_keys=True)
                gateway = Gateway(AssistantMessage(role="assistant",content="Please clarify your read request."))
                ModelAdapter(context(gateway),model="offline/read-model").decide(legacy)
                sent = json.dumps([m.model_dump() for m in gateway.calls[0]["messages"]])
                self.assertNotIn("private-provider-error-marker",sent)
                self.assertNotIn("private-foreign-owner-marker",sent)
                self.assertEqual(snapshot,json.dumps(legacy,sort_keys=True))
                tools = [r for m in gateway.calls[0]["messages"] if isinstance(m,MultiToolMessage) for r in m.tool_messages]
                self.assertEqual(tools[-1].id,call.calls[0].id)
                self.assertEqual(tools[-1].error,error)

    def test_direct_message_conversion_removes_error_body_but_keeps_id(self):
        history = [{"role":"assistant","content":"","tool_calls":[{"id":"err-a","name":"get_item","arguments":{}}]},
                   {"role":"tool","id":"err-a","content":"secret-diagnostic-marker","error":True}]
        messages = sdk_messages(history)
        result = messages[-1].tool_messages[0]
        self.assertEqual(result.id,"err-a")
        self.assertTrue(result.error)
        self.assertNotIn("secret-diagnostic-marker",result.content)

    def test_eight_read_tools_and_internal_address_write_have_real_schemas(self):
        tools = CustomerTools(ReadFake()).get_tools()
        reads = {"lookup_customer", "verify_customer", "read_customer_profile", "get_order", "list_customer_orders", "list_products", "get_product", "get_item"}
        writes = {"address_workflow"}
        self.assertEqual(set(tools), reads | writes)
        for tool in tools.values():
            schema = tool.openai_schema
            self.assertEqual(schema["type"], "function")
            self.assertEqual(schema["function"]["name"], tool.name)
            self.assertEqual(tool.info.get("mutates_state", False), tool.name in writes)
        for name in writes:
            parameters = tools[name].openai_schema["function"]["parameters"]
            self.assertEqual(parameters["required"], ["session_json"])
            self.assertEqual(set(parameters["properties"]), {"session_json"})
            self.assertEqual(parameters["properties"]["session_json"]["type"], "string")

    def test_native_client_and_fresh_toolkits_replay_same_owned_read(self):
        results, traces = [], []
        for _ in range(2):
            backend = ReadFake()
            def transport(payload):
                response = backend.request(payload["method"], payload["path"], body=payload.get("body"))
                return {"status_code": response.status_code, "body": response.body, "headers": {}, "elapsed_seconds": 0.0}
            api = ClientAPI(transport, context=ClientAPIContext(conversation_id="offline-conversation"))
            results.append(CustomerTools(api).get_order(order_id="#TEST1", customer_id="customer_a", email="a@example.test"))
            traces.append(backend.calls)
        self.assertEqual(results[0], results[1])
        self.assertEqual(traces[0], traces[1])

    def test_json_history_restores_real_messages_ids_errors_and_batches(self):
        history = [{"role":"user", "content":"read"},
                   {"role":"assistant", "content":"", "tool_call_ids":["a","b"],
                    "tool_calls":[{"id":"a","name":"get_item","arguments":{"item_id":"x"}}, {"id":"b","name":"get_item","arguments":{"item_id":"y"}}]},
                   {"role":"tools", "tool_messages":[{"role":"tool","id":"b","content":"failure","error":True}, {"role":"tool","id":"a","content":"{}","error":False}]}]
        restored = sdk_messages(json.loads(json.dumps(history)))
        self.assertIsInstance(restored[1], UserMessage)
        self.assertIsInstance(restored[2], AssistantMessage)
        self.assertEqual([c.id for c in restored[2].tool_calls], ["a","b"])
        self.assertIsInstance(restored[3], MultiToolMessage)
        self.assertEqual([r.id for r in restored[3].tool_messages], ["b","a"])
        self.assertTrue(restored[3].tool_messages[0].error)

    def test_missing_mismatched_or_duplicate_history_results_refuse_gateway(self):
        prefix = [{"role":"assistant","tool_call_ids":["a"],"tool_calls":[{"id":"a","name":"get_item","arguments":{}}],"content":""}]
        for outcomes in ([], [{"id":"wrong","content":"{}","error":False}], [{"id":"a","content":"{}","error":False}]*2):
            history = prefix + ([{"role":"tools","tool_messages":outcomes}] if outcomes else [])
            with self.subTest(outcomes=outcomes), self.assertRaises(InvalidAction):
                sdk_messages(history)

    def test_model_reply_calls_round_trip_into_json_state_and_real_tool_results(self):
        backend, state = verified_state()
        gateway = Gateway(AssistantMessage(role="assistant", tool_calls=[ToolCall(id="m-item",name="get_item",arguments={"item_id":"item_blue"}),
                                                                        ToolCall(id="m-product",name="get_product",arguments={"product_id":"product_mug"})], usage={"prompt_tokens":7,"completion_tokens":3}, cost=0.0))
        adapter = ModelAdapter(context(gateway), model="offline/read-model")
        agent = CustomerAgent(model_adapter=adapter)
        prior = json.dumps(state, sort_keys=True)
        outgoing, waiting = agent.generate_next_message(UserMessage(role="user", content="Compare the mug choices for me"), state)
        self.assertEqual([c.id for c in outgoing.tool_calls], ["m-item","m-product"])
        self.assertEqual(prior, json.dumps(state, sort_keys=True))
        self.assertEqual(waiting, json.loads(json.dumps(waiting)))
        request = gateway.calls[0]
        self.assertEqual(request["model"], "offline/read-model")
        self.assertNotIn("max_tokens", request)
        self.assertTrue(all(type(t).__name__ == "Tool" for t in request["actions"]))
        self.assertEqual(waiting["model_usage"][-1]["total_tokens"], 10)
        toolkit = CustomerTools(backend)
        results = [ToolMessage(role="tool", id=c.id, content=json.dumps(getattr(toolkit,c.name)(**c.arguments)), error=False) for c in outgoing.tool_calls]
        response, done = agent.generate_next_message(MultiToolMessage(role="tool",tool_messages=list(reversed(results))), waiting)
        self.assertIn("available variants", response.content)
        self.assertFalse(done["pending_calls"])
        self.assertEqual(done, json.loads(json.dumps(done)))
        sdk_messages(done["history"])
        self.assertEqual(len(gateway.calls), 1)

    def test_writes_unknown_tools_foreign_accounts_or_orders_are_rejected(self):
        _, state = verified_state()
        for name,args in (("cancel_order",{}), ("invented_tool",{}), ("get_order",{"order_id":"#TEST2"}), ("get_item",{"item_id":"item_blue","customer_id":"customer_b"})):
            gateway = Gateway(AssistantMessage(role="assistant", tool_calls=[ToolCall(id="m",name=name,arguments=args)]))
            with self.subTest(name=name), self.assertRaises(InvalidAction):
                ModelAdapter(context(gateway),model="offline/read-model").decide(state)

    def test_mixed_text_calls_duplicate_ids_and_nonassistant_requestors_fail(self):
        _, state = verified_state()
        call = ToolCall(id="dup", name="list_products",arguments={})
        replies = (AssistantMessage(role="assistant",content="done",tool_calls=[call]),
                   AssistantMessage(role="assistant",tool_calls=[call,call]),
                   AssistantMessage(role="assistant",tool_calls=[ToolCall(id="user",name="list_products",arguments={},requestor="user")]))
        for response in replies:
            with self.subTest(response=response), self.assertRaises(InvalidAction):
                ModelAdapter(context(Gateway(response)),model="offline/read-model").decide(state)

    def test_allowlist_fixed_options_and_one_of_are_checked_before_calls(self):
        ctx = context()
        with self.assertRaises(ValueError):
            ModelAdapter(ctx,model="other-model")
        with self.assertRaises(ValueError):
            ModelAdapter(ctx,model="offline/read-model",choices={"max_tokens":1})
        ctx.model_gateway.models = (SimpleNamespace(model="offline/read-model",constrained_args={"max_tokens":1024,"temperature":{"one_of":[0.0,0.5]}}),)
        with self.assertRaises(ValueError):
            ModelAdapter(ctx,model="offline/read-model")
        with self.assertRaises(ValueError):
            ModelAdapter(ctx,model="offline/read-model",choices={"temperature":1.0})
        ModelAdapter(ctx,model="offline/read-model",choices={"temperature":0.0})
        self.assertFalse(ctx.model_gateway.calls)

    def test_empty_bad_output_and_provider_exception_never_create_calls(self):
        _, state = verified_state()
        for response in (None, {}, AssistantMessage(role="assistant",content=" "), UserMessage(role="user",content="Do not convert my role")):
            with self.subTest(response=response), self.assertRaises(InvalidAction):
                ModelAdapter(context(Gateway(response)),model="offline/read-model").decide(state)
        adapter = ModelAdapter(context(Gateway(failure=TimeoutError("private provider text"))),model="offline/read-model")
        with self.assertRaises(ModelGatewayFailure) as caught:
            adapter.decide(state)
        self.assertNotIn("private", str(caught.exception))
        decision, after = advance(TurnInput(kind="user",content="Compare choices"),state,model_adapter=adapter)
        self.assertFalse(decision.calls)
        self.assertEqual(after["model_calls_since_user"],1)

    def test_usage_missing_is_unknown_not_zero_and_cost_zero_is_only_reported(self):
        for usage,total in ((None,None), ({"prompt_tokens":2},None), ({"completion_tokens":3},None), ({"prompt_tokens":2,"completion_tokens":3},5), ({"prompt_tokens":True,"completion_tokens":3},None)):
            result=usage_record(AssistantMessage(role="assistant",content="ok",usage=usage,cost=0.0))
            self.assertEqual(result["total_tokens"],total)
            self.assertEqual(result["reported_cost"],0.0)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RealSDKChecks))
    if result.wasSuccessful() and not result.skipped and result.testsRun > 0 and not network_attempts:
        print(f"REAL_SDK_CHECKS_PASSED {result.testsRun}; skipped 0; model gateway was fake; network attempts 0")
        raise SystemExit(0)
    raise SystemExit(1)
