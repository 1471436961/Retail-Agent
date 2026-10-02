"""State, confirmation boundary and turn protocol tests without tau2."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.adapters.customer_api import verify_and_read_customer
from support_agent.protocol import Decision, InvalidAction, ToolAction, ToolOutcome, TurnInput, decision_from_candidate, select_candidate
from support_agent.state import InvalidState, clone_state, initial_state
from support_agent.turns import advance
from fakes import FakeClientAPI, ScriptedGateway


class SessionTests(unittest.TestCase):
    def test_t1_round_trip_keeps_identity_and_original_state_isolated(self):
        initial = initial_state()
        decision, waiting = advance(TurnInput(kind="user", content="Find customer_a. My email is a@example.test"), initial)
        self.assertEqual(decision.calls[0].name, "lookup_customer")
        self.assertIsNone(decision.text)
        self.assertIsNone(initial["pending_call_id"])
        api = FakeClientAPI()
        record = verify_and_read_customer(api, **decision.calls[0].arguments)
        result = ToolOutcome(id=decision.calls[0].id, content=json.dumps(record))
        reply, finished = advance(TurnInput(kind="tools", outcomes=(result,)), json.loads(json.dumps(waiting)))
        self.assertIn("a@example.test", reply.text)
        self.assertFalse(reply.calls)
        self.assertEqual(finished["identity"], {"verified": True, "customer_id": "customer_a"})
        self.assertIsNone(finished["pending_call_id"])
        self.assertEqual(finished["operations"][0]["status"], "succeeded")
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(json.loads(json.dumps(finished)), finished)

    def test_history_restore_is_json_only_and_does_not_reissue_old_calls(self):
        history = [
            {"role": "user", "content": "Find customer_a"},
            {"role": "assistant", "tool_calls": [{"id": "old-1"}]},
            {"role": "tool", "id": "old-1", "content": "{}", "error": False},
        ]
        state = initial_state(history)
        self.assertEqual(len(state["history"]), 3)
        self.assertEqual(state["history"][1]["tool_call_ids"], ["old-1"])
        self.assertEqual(state["operations"], [])
        self.assertFalse(state["identity"]["verified"])
        self.assertIsNone(state["pending_call_id"])
        self.assertEqual(clone_state(state), state)

    def test_history_rebuilds_known_pending_and_completed_lookup_without_replay(self):
        call = {"id": "lookup-9", "name": "lookup_customer", "arguments": {"customer_id": "customer_a", "email": "a@example.test"}}
        prefix = [
            {"role": "user", "content": "customer_a a@example.test"},
            {"role": "assistant", "tool_calls": [call]},
        ]
        pending = initial_state(prefix)
        self.assertEqual(pending["pending_call_id"], "lookup-9")
        self.assertEqual(pending["operations"][0]["status"], "sent")
        result = ToolOutcome(id="lookup-9", content=json.dumps({"customer_id": "customer_a", "email": "a@example.test"}))
        reply, done = advance(TurnInput(kind="tools", outcomes=(result,)), pending)
        self.assertIn("a@example.test", reply.text)
        self.assertTrue(done["identity"]["verified"])
        completed = initial_state(prefix + [{"role": "tool", "id": "lookup-9", "content": result.content, "error": False}])
        self.assertEqual(completed["operations"][0]["status"], "succeeded")
        self.assertIsNone(completed["pending_call_id"])
        next_decision, later = advance(TurnInput(kind="user", content="customer_a a@example.test"), completed)
        self.assertEqual(next_decision.calls[0].id, "lookup-10")
        self.assertEqual(len(later["operations"]), 2)

    def test_mismatched_or_duplicate_results_never_verify_identity(self):
        decision, waiting = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
        call_id = decision.calls[0].id
        wrong = ToolOutcome(id=call_id, content=json.dumps({"customer_id": "customer_b", "email": "b@example.test"}))
        reply, after = advance(TurnInput(kind="tools", outcomes=(wrong,)), waiting)
        self.assertIn("did not match", reply.text)
        self.assertFalse(after["identity"]["verified"])
        self.assertEqual(after["operations"][0]["status"], "unknown")
        good = ToolOutcome(id=call_id, content=json.dumps({"customer_id": "customer_a", "email": "a@example.test"}))
        reply, duplicate = advance(TurnInput(kind="tools", outcomes=(good, good)), waiting)
        self.assertIn("ambiguous", reply.text)
        self.assertFalse(duplicate["identity"]["verified"])
        missing_id = ToolOutcome(id=call_id, content=json.dumps({"email": "a@example.test"}))
        reply, incomplete = advance(TurnInput(kind="tools", outcomes=(missing_id,)), waiting)
        self.assertIn("did not match", reply.text)
        self.assertFalse(incomplete["identity"]["verified"])

    def test_unrelated_or_missing_tool_result_does_not_consume_as_success(self):
        decision, waiting = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
        stray = ToolOutcome(id="someone-else", content='{"email":"a@example.test"}')
        reply, missing = advance(TurnInput(kind="tools", outcomes=(stray,)), waiting)
        self.assertIn("missing", reply.text)
        self.assertEqual(missing["operations"][0]["status"], "unknown")
        self.assertIsNone(missing["pending_call_id"])
        late, after_late = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(id=decision.calls[0].id, content='{}'),)), missing)
        self.assertIn("No customer lookup", late.text)
        self.assertFalse(after_late["identity"]["verified"])
        good = ToolOutcome(id=decision.calls[0].id, content=json.dumps({"customer_id": "customer_a", "email": "a@example.test"}))
        reply, mixed = advance(TurnInput(kind="tools", outcomes=(stray, good)), waiting)
        self.assertIn("ambiguous", reply.text)
        self.assertFalse(mixed["identity"]["verified"])

    def test_tool_error_does_not_claim_customer_is_missing(self):
        decision, waiting = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
        outcome = ToolOutcome(id=decision.calls[0].id, content="transport timeout", error=True)
        reply, state = advance(TurnInput(kind="tools", outcomes=(outcome,)), waiting)
        self.assertIn("lookup failed", reply.text)
        self.assertNotIn("could not find", reply.text)
        self.assertEqual(state["operations"][0]["status"], "failed")
        self.assertFalse(state["identity"]["verified"])

    def test_new_user_turn_never_replays_pending_call(self):
        _, waiting = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
        decision, next_state = advance(TurnInput(kind="user", content="Please wait"), waiting)
        self.assertFalse(decision.calls)
        self.assertEqual(next_state["operations"][0]["status"], "unknown")
        self.assertIsNone(next_state["pending_call_id"])

    def test_states_are_independent_and_non_json_values_are_rejected(self):
        first, second = initial_state(), initial_state()
        first["tasks"].append({"order_id": "#TEST1"})
        self.assertEqual(second["tasks"], [])
        first["identity"]["verified"] = True
        self.assertFalse(second["identity"]["verified"])
        first["bad"] = object()
        with self.assertRaises(InvalidState):
            clone_state(first)

    def test_internal_history_rebuilds_pending_and_completed_state(self):
        decision, waiting = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
        self.assertEqual(initial_state(waiting["history"]), waiting)
        result = ToolOutcome(id=decision.calls[0].id, content=json.dumps({"customer_id": "customer_a", "email": "a@example.test"}))
        _, done = advance(TurnInput(kind="tools", outcomes=(result,)), waiting)
        self.assertEqual(initial_state(done["history"]), done)

    def test_restoration_uses_the_same_result_batch_rules_as_live_turns(self):
        call = {"id": "lookup-1", "name": "lookup_customer", "arguments": {"customer_id": "customer_a", "email": "a@example.test"}}
        prefix = [{"role": "user", "content": "customer_a a@example.test"}, {"role": "assistant", "tool_calls": [call]}]
        good = ToolOutcome(id="lookup-1", content=json.dumps({"customer_id": "customer_a", "email": "a@example.test"}))
        stray = ToolOutcome(id="other", content=good.content)
        mismatch = ToolOutcome(id="lookup-1", content=json.dumps({"customer_id": "customer_b", "email": "b@example.test"}))
        error = ToolOutcome(id="lookup-1", content="timeout", error=True)
        for outcomes in ((good,), (good, good), (stray,), (good, stray), (stray, good), (), (mismatch,), (error,)):
            with self.subTest(outcomes=outcomes):
                _, live = advance(TurnInput(kind="tools", outcomes=outcomes), initial_state(prefix))
                entries = [{"role": "tool", "id": item.id, "content": item.content, "error": item.error} for item in outcomes]
                restored = initial_state(prefix + [{"tool_messages": entries}])
                for key in ("identity", "operations", "pending_calls", "pending_call_id"):
                    self.assertEqual(restored[key], live[key])
                self.assertEqual(initial_state(live["history"])["identity"], live["identity"])
        # Some callers pass flattened ToolMessages instead of the wrapper.
        duplicate = {"role": "tool", "id": good.id, "content": good.content, "error": False}
        restored = initial_state(prefix + [duplicate, duplicate])
        self.assertFalse(restored["identity"]["verified"])
        self.assertEqual(restored["operations"][0]["status"], "unknown")

    def test_invalid_restored_calls_never_create_pending_slots(self):
        for call in (
            {"id": "", "name": "lookup_customer", "arguments": {"customer_id": "customer_a", "email": "a@example.test"}},
            {"id": "lookup-1", "name": "lookup_customer", "arguments": {"customer_id": "customer_a", "email": "invalid"}},
            {"id": "lookup-1", "name": "delete_order", "arguments": {}},
        ):
            with self.subTest(call=call):
                restored = initial_state([{"role": "assistant", "tool_calls": [call]}])
                self.assertIsNone(restored["pending_call_id"])
                self.assertEqual(restored["pending_calls"], {})
                self.assertFalse(restored["identity"]["verified"])

    def test_malformed_state_is_rejected_at_the_boundary(self):
        for key in ("turn", "operations", "identity", "pending_call_id", "tasks", "handoff"):
            with self.subTest(missing=key):
                state = initial_state()
                del state[key]
                with self.assertRaises(InvalidState):
                    advance(TurnInput(kind="user", content="hello"), state)
        for key, value in (("pending_call_id", ""), ("turn", True), ("operations", [{}]), ("pending_calls", {"orphan": {}})):
            with self.subTest(key=key, value=value):
                state = initial_state()
                state[key] = value
                with self.assertRaises(InvalidState):
                    clone_state(state)

    def test_actual_single_message_call_limit_is_enforced(self):
        calls = tuple(ToolAction(id=f"limit-{i}", name="lookup_customer", arguments={"customer_id": "", "email": "a@example.test"}) for i in range(9))
        self.assertEqual(len(Decision(calls=calls[:8]).calls), 8)
        with self.assertRaisesRegex(InvalidAction, "Too many"):
            Decision(calls=calls)

    def test_candidate_gateway_gate_rejects_unknown_tools_and_mixed_messages(self):
        fake = ScriptedGateway([
            {"type": "reply", "text": "I can look that up."},
            {"type": "tool", "name": "delete_order", "arguments": {}},
        ])
        self.assertEqual(decision_from_candidate(fake.next_candidate(), call_id="m1").text, "I can look that up.")
        with self.assertRaises(InvalidAction):
            decision_from_candidate(fake.next_candidate(), call_id="m2")
        with self.assertRaises(InvalidAction):
            Decision(text="done", calls=(ToolAction(id="m3", name="lookup_customer", arguments={"customer_id": "", "email": "a@example.test"}),))
        with self.assertRaises(InvalidAction):
            decision_from_candidate({"type": "tool", "name": "lookup_customer", "arguments": {"email": "a@example.test", "customer_id": "", "confirmed": "true"}}, call_id="m4")
        with self.assertRaises(InvalidAction):
            decision_from_candidate({"type": "tool", "name": "lookup_customer", "arguments": {"email": "", "customer_id": "customer_a"}}, call_id="m5")
        self.assertEqual(fake.calls, 2)

    def test_invalid_candidates_have_a_bounded_safe_fallback(self):
        gateway = ScriptedGateway([{"type": "tool", "name": "delete_order", "arguments": {}}, {"type": "tool", "name": "delete_order", "arguments": {}}])
        decision = select_candidate(gateway.next_candidate, call_id="m1", max_attempts=2)
        self.assertIn("cannot safely", decision.text)
        self.assertFalse(decision.calls)
        self.assertEqual(gateway.calls, 2)


if __name__ == "__main__":
    unittest.main()
