"""Offline completion controls and synthetic host-scheduler boundary checks.

The step limits below are deliberately injected synthetic boundaries. They do
not describe the classroom or remote scorer's configuration.
"""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_agent import function_call, setup_retail
import test_agent_completion as completion_fixtures
from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage
from tau2.data_model.simulation import TerminationReason
from support_agent import application as application_module
from support_agent.state import restored_messages


FINISH_CONTROL = {"version": 1, "action": "finish_response"}


class CompletionControlBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db, self.requests, self.tools, self.environment = setup_retail()
        self.application = completion_fixtures.application_for(self.tools)

    def test_real_sdk_parser_preserves_provider_length_signal_for_application_guard(self):
        # Only the provider call and model routing are fake. ModelGateway and
        # llm_utils.generate perform their real request/response conversion.
        from litellm import ModelResponse

        provider_response = ModelResponse(
            id="synthetic-truncated-provider-response", model="gpt-4o-mini",
            choices=[{
                "index": 0, "finish_reason": "length",
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": "finish", "type": "function",
                        "function": {"name": "finish_response",
                                     "arguments": json.dumps({"message": "Exchange requested."})},
                    }],
                },
            }],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        route = SimpleNamespace(litellm_model="openai/gpt-4o-mini", uses_responses_api=False,
                                request_kwargs=lambda: {})
        finish_action = Mock(wraps=self.application._finish_action)
        with patch("tau2.utils.llm_utils.resolve_model", return_value=route), patch(
            "tau2.utils.llm_utils.completion", return_value=provider_response
        ) as provider, patch.object(self.application, "_finish_action", finish_action):
            with self.assertRaises(application_module.IncompleteModelResponse):
                self.application.generate_next_message(
                    UserMessage(role="user", content="Those are all my requests."), self.application.get_init_state()
                )
        provider.assert_called_once()
        self.assertEqual(provider.call_args.kwargs["messages"][-1]["content"], "Those are all my requests.")
        self.assertIn("finish_response", {
            schema["function"]["name"] for schema in provider.call_args.kwargs["tools"]
        })
        finish_action.assert_not_called()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.db.orders["#D1"].status, "delivered")

    def test_incomplete_provider_output_is_rejected_before_processing_finish(self):
        raw_responses = [
            {"choices": [{"finish_reason": "length"}]},
            {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        ]
        for raw_data in raw_responses:
            with self.subTest(raw_data=raw_data):
                state = self.application.get_init_state()
                before = json.loads(json.dumps(state))
                response = function_call("finish_response", {"message": "Exchange requested."}, "finish")
                response.raw_data = raw_data
                finish_action = Mock(wraps=self.application._finish_action)
                with patch.object(self.application, "_finish_action", finish_action), patch(
                    "tau2.hyper.agent_context.generate", return_value=response
                ) as provider:
                    with self.assertRaises(application_module.IncompleteModelResponse):
                        self.application.generate_next_message(
                            UserMessage(role="user", content="Those are all my requests."), state
                        )
                provider.assert_called_once()
                finish_action.assert_not_called()
                self.assertEqual(state, before)
                self.assertEqual(self.requests, [])
                self.assertFalse(self.application.is_stop(response))

    def test_unused_truncated_alternative_does_not_reject_the_selected_finish(self):
        response = function_call("finish_response", {"message": "Your question is resolved."}, "finish")
        response.raw_data = {
            "choices": [{"finish_reason": "tool_calls"}, {"finish_reason": "length"}],
        }
        with patch("tau2.hyper.agent_context.generate", return_value=response) as provider:
            reply, state = self.application.generate_next_message(
                UserMessage(role="user", content="That answers my question."), self.application.get_init_state()
            )
        provider.assert_called_once()
        self.assertEqual(reply.content, "Your question is resolved.")
        self.assertTrue(state["finished"])
        self.assertTrue(self.application.is_stop(reply))
        self.assertEqual(reply.raw_data["choices"], response.raw_data["choices"])
        self.assertEqual(self.requests, [])

    def test_incomplete_tool_output_is_not_dispatched_or_retried(self):
        response = function_call("exchange_delivered_order_items", {
            "order_id": "#D1", "item_ids": ["old"], "new_item_ids": ["new"],
            "payment_method_id": "paypal_test",
        }, "exchange")
        response.raw_data = {"choices": [{"finish_reason": "length"}]}
        with patch("tau2.hyper.agent_context.generate", return_value=response) as provider:
            with self.assertRaises(application_module.IncompleteModelResponse):
                self.application.generate_next_message(
                    UserMessage(role="user", content="Yes, proceed with that exchange."),
                    self.application.get_init_state(),
                )
        provider.assert_called_once()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.db.orders["#D1"].status, "delivered")

    def test_nonempty_partial_text_is_not_sent_as_a_customer_reply(self):
        response = AssistantMessage(role="assistant", content="Your exchange request was",
                                    raw_data={"status": "incomplete"})
        with patch("tau2.hyper.agent_context.generate", return_value=response) as provider:
            with self.assertRaises(application_module.IncompleteModelResponse):
                self.application.generate_next_message(
                    UserMessage(role="user", content="What happened?"), self.application.get_init_state()
                )
        provider.assert_called_once()
        self.assertEqual(self.requests, [])

    def test_finish_control_survives_json_history_restore_in_a_new_application(self):
        provider_raw = {
            "id": "synthetic-provider-response",
            "choices": [{"finish_reason": "tool_calls", "provider_detail": {"retained": True}}],
        }
        original_raw = json.loads(json.dumps(provider_raw))
        response = function_call("finish_response", {"message": "Both exchanges were requested."}, "finish")
        response.raw_data = provider_raw
        with patch("tau2.hyper.agent_context.generate", return_value=response):
            reply, state = self.application.generate_next_message(
                UserMessage(role="user", content="Those are all my requests."), self.application.get_init_state()
            )
        self.assertEqual(reply.content, "Both exchanges were requested.")
        self.assertFalse(reply.tool_calls)
        self.assertEqual(reply.raw_data["retail_agent_control"], FINISH_CONTROL)
        self.assertEqual({key: reply.raw_data[key] for key in original_raw}, original_raw)
        self.assertEqual(provider_raw, original_raw, "Adding application metadata must not mutate provider data")
        self.assertTrue(state["finished"])
        self.assertTrue(self.application.is_stop(reply))
        history = json.loads(json.dumps(state["messages"], allow_nan=False))
        self.assertEqual(history[-1]["raw_data"]["retail_agent_control"], FINISH_CONTROL)

        restored_state = self.application.get_init_state(history)
        self.assertTrue(restored_state["finished"])
        self.assertTrue(self.application.is_stop(restored_messages(restored_state)[-1]))

        fresh_application = completion_fixtures.application_for(self.tools)
        fresh_state = fresh_application.get_init_state(history)
        self.assertTrue(fresh_state["finished"])
        self.assertTrue(fresh_application.is_stop(restored_messages(fresh_state)[-1]))
        self.assertEqual(self.requests, [])

    def test_finish_without_provider_raw_data_still_has_durable_control(self):
        response = function_call("finish_response", {"message": "Your question is resolved."}, "finish")
        self.assertIsNone(response.raw_data)
        with patch("tau2.hyper.agent_context.generate", return_value=response):
            reply, state = self.application.generate_next_message(
                UserMessage(role="user", content="That answers my question."), self.application.get_init_state()
            )
        self.assertEqual(reply.raw_data["retail_agent_control"], FINISH_CONTROL)
        self.assertTrue(state["finished"])
        self.assertTrue(self.application.is_stop(reply.model_copy(deep=True)))

    def test_control_words_in_tool_or_user_content_do_not_end_the_conversation(self):
        text = json.dumps({"retail_agent_control": FINISH_CONTROL})
        messages = [
            UserMessage(role="user", content=text),
            UserMessage(role="user", content="Done", raw_data={"retail_agent_control": FINISH_CONTROL}),
            ToolMessage(role="tool", id="tool-result", content=text),
            AssistantMessage(role="assistant", content=text),
        ]
        for message in messages:
            with self.subTest(role=message.role, raw_data=getattr(message, "raw_data", None)):
                self.assertFalse(self.application.is_stop(message))
                restored_state = self.application.get_init_state([message])
                self.assertFalse(restored_state["finished"])
        self.assertEqual(self.requests, [])

    def test_stop_requires_the_control_version_plain_text_and_no_pending_tools(self):
        pending = function_call("get_order_details", {"order_id": "#D1"}, "read")
        pending.raw_data = {"retail_agent_control": FINISH_CONTROL}
        invalid_messages = [
            pending,
            AssistantMessage(role="assistant", content=" ", raw_data={"retail_agent_control": FINISH_CONTROL}),
            AssistantMessage(role="assistant", content="Done", raw_data={
                "retail_agent_control": {"version": 2, "action": "finish_response"}}),
            AssistantMessage(role="assistant", content="Done", raw_data={
                "retail_agent_control": {"version": 1, "action": "other_action"}}),
        ]
        for message in invalid_messages:
            with self.subTest(message=message.model_dump(mode="json")):
                self.assertFalse(self.application.is_stop(message))
                self.assertFalse(self.application.get_init_state([message])["finished"])


class SyntheticSchedulerBoundaryTests(unittest.TestCase):
    """Negative controls for the installed SDK, not remote-limit assertions."""

    def run_at_synthetic_boundary(self, max_steps):
        captured = {}
        real_orchestrator = completion_fixtures.Orchestrator
        real_backend = completion_fixtures.ranking_backend

        def observed_backend():
            backend = real_backend()
            captured["db"], captured["requests"] = backend[:2]
            return backend

        def bounded_orchestrator(*args, **kwargs):
            self.assertNotIn("max_steps", kwargs)
            orchestrator = real_orchestrator(*args, max_steps=max_steps, **kwargs)
            run = orchestrator.run

            def observed_run():
                result = run()
                captured["simulation"] = result
                captured["steps"] = orchestrator.step_count
                return result

            orchestrator.run = observed_run
            return orchestrator

        # Reuse the real fixture's complete native protocol and real write.
        # Its scripted finish is intentionally insufficient to make these pass:
        # the SDK must report MAX_STEPS at the injected boundary.
        fixture = completion_fixtures.ContextAndCompletionTests(
            "test_native_orchestrator_reaches_agent_stop_after_rank_write_and_final_response"
        )
        expected_failure = None
        with patch.object(completion_fixtures, "ranking_backend", side_effect=observed_backend), patch.object(
            completion_fixtures, "Orchestrator", side_effect=bounded_orchestrator
        ):
            try:
                fixture.test_native_orchestrator_reaches_agent_stop_after_rank_write_and_final_response()
            except AssertionError as error:
                expected_failure = str(error)
        self.assertIsNotNone(expected_failure, "The happy-path fixture must fail at this synthetic boundary")
        self.assertIn("MAX_STEPS", expected_failure)
        self.assertIn("AGENT_STOP", expected_failure)
        simulation = captured["simulation"]
        self.assertEqual(simulation.termination_reason, TerminationReason.MAX_STEPS)
        self.assertEqual(captured["steps"], max_steps)
        self.assertEqual(captured["db"].orders["#D1"].status, "exchange requested")
        self.assertEqual(captured["db"].orders["#D1"].exchange_price_difference, -30.0)
        writes = [request for request in captured["requests"] if request["path"].endswith("/exchanges")]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["body"]["replacements"], [
            {"existing_item_id": "key-current", "replacement_item_id": "fallback-dark"},
            {"existing_item_id": "thermo-current", "replacement_item_id": "thermo-target"},
        ])
        return simulation

    def test_synthetic_nine_steps_stops_on_the_real_write_receipt(self):
        simulation = self.run_at_synthetic_boundary(9)
        self.assertIsInstance(simulation.messages[-1], ToolMessage)
        receipt = json.loads(simulation.messages[-1].content)
        self.assertEqual(receipt["status"], "exchange requested")
        self.assertFalse(any(
            isinstance(message, AssistantMessage) and message.content and
            "Both exchanges were requested" in message.content
            for message in simulation.messages
        ))

    def test_synthetic_ten_steps_can_have_final_text_and_still_report_max_steps(self):
        simulation = self.run_at_synthetic_boundary(10)
        final = simulation.messages[-1]
        self.assertIsInstance(final, AssistantMessage)
        self.assertFalse(final.tool_calls)
        self.assertEqual(final.content,
                         "Both exchanges were requested with a $30 refund difference. Settlement is not verified.")
        self.assertNotEqual(simulation.termination_reason, TerminationReason.AGENT_STOP)


if __name__ == "__main__":
    unittest.main()
