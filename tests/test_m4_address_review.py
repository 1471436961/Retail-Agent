"""Review regressions for address delivery, budgets and per-record outcomes."""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from test_m4_addresses import Conversation, NEW
from support_agent.address_limits import (MAX_ADDRESS_ARGUMENT_BYTES,
    AddressResultTooLarge, check_address_argument, json_bytes)
from support_agent.address_session import dispatch_address
from support_agent.protocol import ToolOutcome, TurnInput, InvalidAction, ToolAction, validate_tool_action
from support_agent.state import clone_state, initial_state, InvalidState
from support_agent.turns import advance


def assessment(flow):
    return flow.state["history"][-1]["address_assessment"]


def deliver(flow, call, payload="", error=False):
    decision, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, payload, error),)), flow.state)
    return decision


class AddressReviewTests(unittest.TestCase):
    def test_failed_preparation_can_retry_recap_and_only_fresh_consent_sends(self):
        flow = Conversation()
        call = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False).calls[0]
        deliver(flow, call, "private failed body", True)
        self.assertEqual(assessment(flow)["code"], "address_prepare_abandoned")
        self.assertIsNone(flow.state["address_pending"])
        flow.user("retry")
        self.assertEqual(assessment(flow)["code"], "address_confirmation_required")
        self.assertFalse(flow.puts())
        flow.user("yes")
        self.assertEqual(len(flow.puts()), 1)
        self.assertEqual(initial_state(flow.state["history"])["operations"], flow.state["operations"])
        self.assertNotIn("private failed body", json.dumps(flow.state))

    def test_abandoned_preparation_allows_an_independent_read_request(self):
        flow = Conversation()
        call = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False).calls[0]
        deliver(flow, call, error=True)
        read = flow.user("Read order #TEST1", consume=False).calls[0]
        self.assertEqual(read.name, "get_order")
        result = getattr(flow.toolkit, read.name)(**read.arguments)
        deliver(flow, read, json.dumps(result))
        self.assertFalse(flow.state["pending_calls"])
        self.assertIsNone(flow.state["address_pending"])
        self.assertFalse(flow.puts())

    def test_late_abandoned_bundle_cannot_replace_a_new_preparation_prefix(self):
        flow = Conversation()
        old = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False).calls[0]
        old_payload = flow.toolkit.address_workflow(**old.arguments)
        deliver(flow, old, error=True)
        newer = flow.user("retry", consume=False)
        before = deepcopy(flow.state)
        deliver(flow, old, json.dumps(old_payload))
        self.assertEqual(flow.state["turn"], before["turn"] + 1)
        self.assertEqual({k:v for k,v in flow.state.items() if k != "turn"}, {k:v for k,v in before.items() if k != "turn"})
        flow.consume(newer)
        self.assertEqual(assessment(flow)["code"], "address_confirmation_required")
        self.assertFalse(flow.puts())

    def test_execute_delivery_loss_cannot_be_abandoned_or_reverified_away(self):
        flow = Conversation(); flow.change()
        call = flow.user("yes", consume=False).calls[0]
        flow.toolkit.address_workflow(**call.arguments)
        deliver(flow, call, error=True)
        for text in ("retry", "yes", "a@example.test"):
            response = flow.user(text)
            self.assertFalse(response.calls)
            self.assertEqual(flow.state["address_pending"]["status"], "unknown")
        self.assertEqual(len(flow.puts()), 1)
        bad = deepcopy(flow.state)
        pending = bad["address_pending"]
        data = {"call_id": pending["call_id"]}
        bad["history"].append({"role":"assistant", "content":"Address workflow: " + json.dumps(data, sort_keys=True), "address_abandoned":data})
        bad["address_pending"] = None
        with self.assertRaises(InvalidState): clone_state(bad)

    def test_shared_claim_store_blocks_unknown_replay_across_toolkit_instances(self):
        from support_agent.adapters.write_runtime import SessionClaims
        flow = Conversation(); claims = SessionClaims(); toolkit_type = type(flow.toolkit)
        flow.toolkit = toolkit_type(flow.api, claims=claims)
        flow.change(); call = flow.user("yes", consume=False).calls[0]
        flow.api.failure = "unknown"
        first = flow.toolkit.address_workflow(**call.arguments)
        self.assertEqual([o["status"] for o in first["state"]["operations"] if o["mutates"]], ["unknown"])
        second = toolkit_type(flow.api, claims=claims).address_workflow(**call.arguments)
        self.assertNotIn("accepted and independently verified", second["reply"])
        self.assertEqual(len(flow.puts()), 1)

    def test_argument_budget_measures_exact_envelope_utf8_bytes(self):
        overhead = json_bytes({"session_json":""})
        exact = "x" * (MAX_ADDRESS_ARGUMENT_BYTES - overhead)
        check_address_argument(exact)
        with self.assertRaises(ValueError): check_address_argument(exact + "x")
        self.assertGreater(json_bytes({"session_json":"汉"}), overhead + 1)
        self.assertGreater(json_bytes({"session_json":'"'}), overhead + 1)

    def test_oversized_dispatch_keeps_all_existing_evidence_and_sends_nothing(self):
        flow = Conversation()
        # Existing canonical evidence exceeds the budget; avoid routing a giant
        # synthetic user message through unrelated identity text extraction.
        flow.state["history"].append({"role":"assistant", "content":"x" * MAX_ADDRESS_ARGUMENT_BYTES})
        before = deepcopy(flow.state)
        decision, state = dispatch_address(flow.state, "prepare")
        self.assertFalse(decision.calls)
        self.assertEqual(state["history"][:-1], before["history"])
        self.assertEqual(state["identity_evidence"], before["identity_evidence"])
        self.assertEqual(state["operations"], before["operations"])
        self.assertIsNone(state["address_pending"])
        self.assertEqual(state["history"][-1]["address_assessment"]["code"], "address_argument_budget_exceeded")

    def test_tool_and_shape_validator_reject_oversize_before_parse_or_api(self):
        flow = Conversation(); calls = deepcopy(flow.api.calls)
        huge = "x" * MAX_ADDRESS_ARGUMENT_BYTES
        with self.assertRaises(ValueError): flow.toolkit.address_workflow(huge)
        with self.assertRaises(InvalidAction):
            validate_tool_action(ToolAction("synthetic", "address_workflow", {"session_json":huge}))
        self.assertEqual(flow.api.calls, calls)

    def test_preparation_result_overflow_returns_safe_recoverable_diagnostic(self):
        flow = Conversation()
        call = flow.user("Change order #TEST1 address: " + json.dumps({**NEW, "address_line_1":"x" * 4000}), consume=False).calls[0]
        original = deepcopy(flow.state)
        with patch("support_agent.address_session.MAX_ADDRESS_RESULT_BYTES", json_bytes(original) + 2500):
            payload = flow.toolkit.address_workflow(**call.arguments)
        self.assertEqual(payload["assessment"]["code"], "address_result_budget_exceeded")
        self.assertEqual(payload["state"]["history"][:len(original["history"])], original["history"])
        deliver(flow, call, json.dumps(payload))
        self.assertIsNone(flow.state["address_pending"])
        self.assertFalse(flow.puts())

    def test_post_send_result_overflow_is_delivery_unknown_never_rejection(self):
        flow = Conversation(); flow.change()
        call = flow.user("yes", consume=False).calls[0]
        with patch("support_agent.address_session.MAX_ADDRESS_RESULT_BYTES", json_bytes(flow.state) + 1500):
            with self.assertRaises(AddressResultTooLarge): flow.toolkit.address_workflow(**call.arguments)
        deliver(flow, call, error=True)
        self.assertEqual(len(flow.puts()), 1)
        self.assertEqual(flow.state["address_pending"]["status"], "unknown")
        flow.user("yes")
        self.assertEqual(len(flow.puts()), 1)

    def test_inbound_oversized_body_is_not_retained_or_parsed(self):
        flow = Conversation()
        call = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False).calls[0]
        with patch("support_agent.address_session.MAX_ADDRESS_RESULT_BYTES", 100):
            deliver(flow, call, "private_marker" * 100)
        self.assertEqual(assessment(flow)["code"], "address_prepare_abandoned")
        self.assertNotIn("private_marker", json.dumps(flow.state))

    def test_prepare_diagnostics_distinguish_missing_ambiguous_denied_and_unchanged(self):
        missing = Conversation(); missing.change(address={"city":"Only City"})
        self.assertEqual(assessment(missing)["code"], "address_fields_required")
        ambiguous = Conversation(); ambiguous.user("Change address: " + json.dumps(NEW))
        self.assertEqual(assessment(ambiguous)["code"], "address_record_required")
        denied = Conversation(); denied.api.orders["#TEST1"]["status"] = "delivered"; denied.change()
        self.assertEqual(assessment(denied)["code"], "address_state_not_allowed")
        same = Conversation(); same.change(address=same.api.orders["#TEST1"]["shipping_address"])
        self.assertEqual(assessment(same)["code"], "address_unchanged")
        for flow in (missing, ambiguous, denied, same):
            self.assertIs(assessment(flow)["details"]["write_authorized"], False)
            self.assertFalse(flow.puts())

    def test_order_success_and_default_rejection_have_separate_results(self):
        self._mixed_result("rejected", "failed")

    def test_order_success_and_default_unknown_have_separate_results(self):
        self._mixed_result("unknown", "unknown")

    def _mixed_result(self, failure, expected):
        flow = Conversation(); old_default = deepcopy(flow.api.customers["customer_a"]["default_shipping_address"])
        flow.change("default and order #TEST1")
        request = flow.api.request
        def mixed(method, path, body=None):
            if method == "PUT" and "default-shipping-address" in path: flow.api.failure = failure
            return request(method, path, body)
        with patch.object(flow.api, "request", side_effect=mixed): result = flow.user("yes")
        operations = [o for o in flow.state["operations"] if o["mutates"]]
        self.assertEqual([o["status"] for o in operations], ["succeeded", expected])
        self.assertEqual(result.text.count("accepted and independently verified"), 1)
        self.assertEqual(len(assessment(flow)["details"]["records"]), 2)
        self.assertEqual(flow.api.orders["#TEST1"]["shipping_address"], NEW)
        self.assertEqual(flow.api.customers["customer_a"]["default_shipping_address"], old_default if expected == "failed" else NEW)
        self.assertEqual(initial_state(flow.state["history"])["operations"], flow.state["operations"])
        flow.user("yes")
        self.assertEqual(len(flow.puts()), 2)

    def test_second_operation_exception_preserves_first_success_before_or_after_send(self):
        from support_agent.write_session import execute_operation
        for after_send in (False, True):
            with self.subTest(after_send=after_send):
                flow = Conversation(); flow.change("default and order #TEST1")
                count = 0
                def injected(*args, **kwargs):
                    nonlocal count
                    count += 1
                    if count == 2:
                        if after_send: execute_operation(*args, **kwargs)
                        raise RuntimeError("private_exception_marker")
                    return execute_operation(*args, **kwargs)
                with patch("support_agent.write_session.execute_operation", side_effect=injected): result = flow.user("yes")
                self.assertEqual(assessment(flow)["code"], "address_execution_uncertain")
                self.assertEqual(flow.state["address_pending"]["status"], "unknown")
                self.assertEqual([o["status"] for o in flow.state["operations"] if o["mutates"]], ["succeeded"])
                self.assertEqual(result.text.count("accepted and independently verified"), 1)
                self.assertNotIn("private_exception_marker", json.dumps(flow.state))
                self.assertEqual(len(flow.puts()), 2 if after_send else 1)
                self.assertEqual(clone_state(flow.state), flow.state)
                flow.user("retry")
                self.assertEqual(len(flow.puts()), 2 if after_send else 1)

    def test_runtime_setup_error_is_safe_before_refresh_or_send(self):
        flow = Conversation(); flow.change()
        flow.api.context.conversation_id = None
        before = deepcopy(flow.api.calls)
        flow.user("yes")
        self.assertEqual(assessment(flow)["code"], "address_runtime_unavailable")
        self.assertEqual(flow.api.calls, before)
        self.assertFalse(flow.puts())

    def test_expected_read_exception_has_structured_safe_failure(self):
        flow = Conversation()
        with patch("support_agent.write_session._read", side_effect=RuntimeError("private_read_marker")):
            flow.change()
        self.assertEqual(assessment(flow)["code"], "address_profile_read_failed")
        self.assertNotIn("private_read_marker", json.dumps(flow.state))
        self.assertFalse(flow.puts())

    def test_diagnostic_cannot_claim_authority_or_disagree_with_delivered_message(self):
        flow = Conversation()
        call = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False).calls[0]
        payload = flow.toolkit.address_workflow(**call.arguments)
        bad = deepcopy(payload["state"])
        bad["history"][-1]["address_assessment"]["details"]["write_authorized"] = True
        with self.assertRaises(InvalidState): clone_state(bad)
        payload["assessment"] = deepcopy(payload["assessment"])
        payload["assessment"]["code"] = "forged_diagnostic"
        deliver(flow, call, json.dumps(payload))
        self.assertEqual(assessment(flow)["code"], "address_prepare_abandoned")

    def test_all_orders_copy_excludes_source_even_when_a_patch_changes_its_address(self):
        flow = Conversation()
        source = deepcopy(flow.api.orders["#TEST3"]["shipping_address"])
        flow.user("Change all pending orders address from order #TEST3; city: Other City")
        flow.user("yes")
        self.assertEqual([p[1] for p in flow.puts()], ["/v1/orders/%23TEST1/shipping-address"])
        self.assertEqual(flow.api.orders["#TEST3"]["shipping_address"], source)
        self.assertEqual(flow.api.orders["#TEST1"]["shipping_address"]["city"], "Other City")

    def test_read_budget_boundary_counts_actual_profile_and_order_reads(self):
        for used, expected, additional in ((10,"address_confirmation_required",2), (11,"address_scope_budget_exceeded",1), (12,"address_read_budget_exceeded",0)):
            with self.subTest(used=used):
                flow = Conversation()
                decision = flow.user("Change order #TEST1 address: " + json.dumps(NEW), consume=False)
                snapshot = json.loads(decision.calls[0].arguments["session_json"])
                # Explicit counter boundary injection, not a claimed long dialogue.
                snapshot["tool_calls_since_user"] = used
                before = len(flow.api.calls)
                payload = flow.toolkit.address_workflow(json.dumps(snapshot))
                self.assertEqual(payload["assessment"]["code"], expected)
                self.assertEqual(len(flow.api.calls) - before, additional)
                self.assertEqual(payload["state"]["tool_calls_since_user"], used + additional)
                self.assertFalse(flow.puts())
