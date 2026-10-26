"""Context loading and explicit model completion through the native turn protocol."""
import json
import unittest
from unittest.mock import patch

from test_agent import ROOT, setup_retail, function_call
from test_preferences import ranking_backend
from tau2.data_model.message import AssistantMessage, MultiToolMessage, UserMessage
from tau2.data_model.simulation import TerminationReason
from tau2.data_model.tasks import Task, UserScenario
from tau2.hyper.agent_context import activate_agent_context, build_agent_context
from tau2.hyper.sandbox.candidate_server import CandidateServer
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.utils.llm_utils import validate_message_history
from tau2.utils.utils import get_now
from agent import create_agent


def application_for(tools):
    context = build_agent_context(domain="retail_plus", tools=list(tools.get_tools().values()),
                                  resource_root=ROOT / "agent", model_configs=[{"model": "offline/completion"}])
    with activate_agent_context(context):
        return create_agent()


class ContextAndCompletionTests(unittest.TestCase):
    def setUp(self):
        self.db, self.requests, self.tools, self.environment = setup_retail()
        self.application = application_for(self.tools)

    def test_name_authentication_returns_profile_and_owned_order_in_one_tool_call(self):
        before = self.db.model_dump(mode="json")
        context = self.tools.get_customer_context(first_name="Casey", last_name="Morgan",
                                                  postal_code="90210", order_ids=["#D1"])
        self.assertEqual(context["customer_id"], "casey")
        self.assertEqual(context["customer"]["payment_methods"][0]["id"], "paypal_test")
        self.assertEqual(context["orders"][0]["order_id"], "#D1")
        self.assertEqual([(r["method"], r["path"]) for r in self.requests],
                         [("POST", "/v1/customers/search"), ("GET", "/v1/customers/casey"),
                          ("GET", "/v1/orders/%23D1")])
        self.assertEqual(self.db.model_dump(mode="json"), before)

    def test_email_authentication_deduplicates_order_reads(self):
        context = self.tools.get_customer_context(email="casey@example.test", order_ids=["#D1", "#D1"])
        self.assertEqual([o["order_id"] for o in context["orders"]], ["#D1"])
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.requests[0]["body"], {"email": "casey@example.test"})

    def test_unowned_order_is_blocked_before_any_order_detail_read(self):
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.tools.get_customer_context(email="casey@example.test", order_ids=["#D1", "#OTHER"])
        self.assertEqual([r["path"] for r in self.requests], ["/v1/customers/search", "/v1/customers/casey"])

    def test_missing_identity_does_not_read_any_customer_data(self):
        with self.assertRaisesRegex(ValueError, "email OR full name"):
            self.tools.get_customer_context(order_ids=["#D1"])
        self.assertEqual(self.requests, [])

    def test_finish_action_becomes_final_text_and_native_is_stop_after_real_write(self):
        write = function_call("exchange_delivered_order_items", {
            "order_id": "#D1", "item_ids": ["old"], "new_item_ids": ["new"],
            "payment_method_id": "paypal_test",
        }, "write")
        history = [UserMessage(role="user", content="Yes, exchange that shirt for red M with PayPal."), write]
        result = self.environment.get_response(write.tool_calls[0])
        self.assertFalse(result.error, result.content)
        server = object.__new__(CandidateServer)
        server.agent = self.application
        server.agent_state = self.application.get_init_state(history)
        final_text = "The exchange was requested with a $3.50 difference. Shipment is not yet confirmed."
        finish = function_call("finish_response", {"message": final_text}, "finish")
        incoming = MultiToolMessage(role="tool", tool_messages=[result])
        def provider(**kwargs):
            validate_message_history(kwargs["messages"])
            self.assertEqual(kwargs["messages"][-1].id, "write")
            self.assertEqual(json.loads(kwargs["messages"][-1].content)["status"], "exchange requested")
            return finish
        before_reads = len(self.requests)
        with patch("tau2.hyper.agent_context.generate", side_effect=provider) as inference:
            reply = server.dispatch("agent_turn", {"message": incoming.model_dump(mode="json")})
        self.assertEqual(inference.call_count, 1)
        self.assertEqual(reply["content"], final_text)
        self.assertFalse(reply.get("tool_calls"))
        self.assertTrue(server.dispatch("agent_is_stop", {"message": reply}))
        self.assertTrue(server.agent_state["finished"])
        self.assertEqual(len(self.requests), before_reads)
        self.assertEqual(self.db.orders["#D1"].status, "exchange requested")
        json.dumps(server.agent_state, allow_nan=False)

    def test_ordinary_reply_does_not_end_conversation_based_on_words(self):
        message = AssistantMessage(role="assistant", content="Before we finish, what else do you need?")
        with patch("tau2.hyper.agent_context.generate", return_value=message):
            reply, state = self.application.generate_next_message(
                UserMessage(role="user", content="I have another request."), self.application.get_init_state())
        self.assertIs(reply, message)
        self.assertFalse(self.application.is_stop(reply))
        self.assertFalse(state["finished"])

    def test_finish_proposed_with_a_write_waits_for_its_actual_result(self):
        write = function_call("exchange_delivered_order_items", {
            "order_id": "#D1", "item_ids": ["old"], "new_item_ids": ["new"],
            "payment_method_id": "paypal_test",
        }, "write")
        finish = function_call("finish_response", {"message": "Everything is done."}, "premature")
        write.tool_calls.extend(finish.tool_calls)
        with patch("tau2.hyper.agent_context.generate", return_value=write):
            reply, state = self.application.generate_next_message(
                UserMessage(role="user", content="Yes, proceed with the exchange."), self.application.get_init_state())
        self.assertEqual([call.name for call in reply.tool_calls], ["exchange_delivered_order_items"])
        self.assertFalse(self.application.is_stop(reply))
        self.assertFalse(state["finished"])
        self.assertEqual(self.requests, [])
        result = self.environment.get_response(reply.tool_calls[0])
        self.assertFalse(result.error, result.content)
        self.assertEqual(len(self.requests), 1)

    def test_empty_finish_is_not_fabricated_into_a_success_message(self):
        finish = function_call("finish_response", {"message": " "})
        with patch("tau2.hyper.agent_context.generate", return_value=finish):
            with self.assertRaisesRegex(ValueError, "final customer-facing"):
                self.application.generate_next_message(UserMessage(role="user", content="Help"),
                                                       self.application.get_init_state())
        self.assertFalse(self.application.is_stop(AssistantMessage(role="assistant", content="Done")))
        self.assertEqual(self.requests, [])

    def test_native_orchestrator_reaches_agent_stop_after_rank_write_and_final_response(self):
        db, requests, tools, environment = ranking_backend()
        application = application_for(tools)
        server = object.__new__(CandidateServer)
        server.agent = application

        class ProtocolAgent:
            def get_init_state(self, message_history=None):
                server.agent_state = application.get_init_state(message_history)
                return {}
            def generate_next_message(self, message, state):
                reply = server.dispatch("agent_turn", {"message": message.model_dump(mode="json")})
                return AssistantMessage.model_validate(reply), state
            def is_stop(self, message):
                return server.dispatch("agent_is_stop", {"message": message.model_dump(mode="json")})
            def stop(self, *args):
                pass

        class Customer:
            def get_init_state(self, message_history=None):
                return 0
            def generate_next_message(self, message, state):
                texts = ["Casey Morgan, 90210. Exchange both on #D1: clicky/no backlight/full size and Google-compatible black thermostat.",
                         "Yes, these are all changes. Proceed with both using PayPal."]
                if state >= len(texts):
                    raise AssertionError("Explicit model completion did not terminate the conversation")
                return UserMessage(role="user", content=texts[state]), state + 1
            def stop(self, *args):
                pass

        rank = function_call("rank_preferred", {"order_id": "#D1", "item_id": "key-current",
                             "allowed_options": {"switch type": ["clicky"], "backlight": ["none"]},
                             "sort_by": []}, "rank-keyboard")
        rank.tool_calls.extend(function_call("rank_preferred", {"order_id": "#D1", "item_id": "thermo-current",
                               "allowed_options": {"compatibility": ["Google Assistant"]},
                               "sort_by": []}, "rank-thermostat").tool_calls)
        replies = iter([
            function_call("get_customer_context", {"first_name": "Casey", "last_name": "Morgan",
                          "postal_code": "90210", "order_ids": ["#D1"]}, "context"),
            rank,
            AssistantMessage(role="assistant", content="Exchange both: full-size clicky/no backlight keyboard and black Google-compatible thermostat. Difference -$30 via PayPal. Is that all, and may I proceed?"),
            function_call("exchange_delivered_order_items", {"order_id": "#D1",
                          "item_ids": ["key-current", "thermo-current"], "new_item_ids": ["fallback-dark", "thermo-target"],
                          "payment_method_id": "paypal_test"}, "exchange"),
            function_call("finish_response", {"message": "Both exchanges were requested with a $30 refund difference. Settlement is not verified."}, "finish"),
        ])
        seen = []
        def provider(**kwargs):
            validate_message_history(kwargs["messages"])
            seen.append(kwargs)
            return next(replies).model_copy(update={"timestamp": get_now()})
        task = Task(id="synthetic-completion", user_scenario=UserScenario(instructions="Synthetic two-item exchange."))
        # Use the SDK defaults; do not invent a classroom step limit.
        orchestrator = Orchestrator(domain="retail_plus", agent=ProtocolAgent(), user=Customer(),
                                    environment=environment, task=task, validate_communication=True)
        with patch("tau2.hyper.agent_context.generate", side_effect=provider):
            simulation = orchestrator.run()
        self.assertEqual(simulation.termination_reason, TerminationReason.AGENT_STOP)
        self.assertEqual(len(seen), 5)
        self.assertEqual(simulation.messages[-1].content,
                         "Both exchanges were requested with a $30 refund difference. Settlement is not verified.")
        self.assertFalse(simulation.messages[-1].tool_calls)
        self.assertEqual(db.orders["#D1"].status, "exchange requested")
        self.assertEqual(db.orders["#D1"].exchange_price_difference, -30.0)
        writes = [r for r in requests if r["path"].endswith("/exchanges")]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["body"]["replacements"], [
            {"existing_item_id": "key-current", "replacement_item_id": "fallback-dark"},
            {"existing_item_id": "thermo-current", "replacement_item_id": "thermo-target"},
        ])
        names = {tool.name for tool in seen[0]["tools"]}
        self.assertTrue({"get_customer_context", "rank_preferred", "finish_response"} <= names)
        self.assertNotIn("find_user_id_by_name_zip", names)


if __name__ == "__main__":
    unittest.main()
