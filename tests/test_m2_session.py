"""Read-only conversation, identity provenance, replay and failure boundaries."""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.adapters.customer_api import verify_and_read_customer
from support_agent.adapters import read_api
from support_agent.protocol import Decision, InvalidAction, ToolAction, ToolOutcome, TurnInput
from support_agent.read_session import advance, bind_arguments, record_decision
from support_agent.state import InvalidState, clone_state, initial_state
from m2_fakes import ReadFake


def execute(api, decision):
    results = []
    for call in decision.calls:
        fn = verify_and_read_customer if call.name == "lookup_customer" else getattr(read_api, "verify_customer" if call.name == "read_customer_profile" else call.name)
        body = fn(api, **call.arguments)
        results.append(ToolOutcome(id=call.id, content=json.dumps(body)))
    return TurnInput(kind="tools", outcomes=tuple(results))


def verified_state():
    api = ReadFake()
    decision, state = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
    _, state = advance(execute(api, decision), state)
    return api, state


class ReadSessionTests(unittest.TestCase):
    def test_profile_query_reads_formats_and_refreshes_only_verified_customer(self):
        for proof in ("a@example.test", "first_name: Alice; last_name: Example; postal_code: 10001"):
            with self.subTest(proof=proof):
                api = ReadFake()
                first, state = advance(TurnInput(kind="user", content=proof), initial_state())
                _, state = advance(execute(api, first), state)
                original = deepcopy(state)
                api.customers["customer_a"]["default_shipping_address"]["city"] = "Updated Testville"
                api.calls.clear()
                call, waiting = advance(TurnInput(kind="user", content="Show my profile and payment methods"), state)
                self.assertEqual(call.calls[0].name, "read_customer_profile")
                self.assertEqual(call.calls[0].arguments["customer_id"], "customer_a")
                self.assertFalse(api.calls)
                answer, done = advance(execute(api, call), waiting)
                self.assertEqual([p for _, p, _ in api.calls], ["/v1/customers/search", "/v1/customers/customer_a"])
                self.assertTrue(answer.text.startswith("Verified customer profile: "))
                profile = json.loads(answer.text.split(": ", 1)[1])
                self.assertEqual(profile["customer_id"], "customer_a")
                self.assertEqual(profile["payment_methods"][0]["id"], "card_a")
                self.assertEqual(profile["default_shipping_address"]["city"], "Updated Testville")
                self.assertEqual(done["customer_record"], profile)
                self.assertEqual(done["identity_evidence"], original["identity_evidence"])
                self.assertEqual(done["identity"], original["identity"])
                self.assertEqual(state, original)
                self.assertEqual(initial_state(done["history"])["customer_record"], profile)

    def test_profile_result_mismatch_preserves_identity_without_disclosing_body(self):
        api, state = verified_state()
        call, waiting = advance(TurnInput(kind="user", content="my profile"), state)
        for field, value in (("customer_id", "customer_b"), ("email", "b@example.test")):
            bad = deepcopy(api.customers["customer_a"])
            bad[field] = value
            bad["private_note"] = "unverified-profile-marker"
            with self.subTest(field=field):
                answer, done = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(id=call.calls[0].id, content=json.dumps(bad)),)), waiting)
                self.assertIn("did not match", answer.text)
                self.assertNotIn("unverified-profile-marker", json.dumps(done))
                self.assertEqual(done["customer_record"], state["customer_record"])
                self.assertEqual(done["identity_evidence"], state["identity_evidence"])
                self.assertEqual(done["operations"][-1]["status"], "unknown")
                self.assertFalse(done["pending_calls"])

    def test_current_model_flow_calls_once_per_request_and_never_on_tool_results(self):
        api, state = verified_state()
        class CountingAdapter:
            def __init__(self):
                self.calls = 0
                self.seen_counters = []
            def decide(self, candidate_state):
                self.calls += 1
                self.seen_counters.append(candidate_state["model_calls_since_user"])
                return Decision(calls=(ToolAction(id=f"model-read-{self.calls}", name="get_product",
                    arguments=bind_arguments("get_product", {"product_id": "product_mug"}, candidate_state)),))
        adapter = CountingAdapter()
        for request_number in (1, 2):
            before = deepcopy(state)
            call, waiting = advance(TurnInput(kind="user", content="Compare the mug options"), state, model_adapter=adapter)
            self.assertEqual(state, before)
            self.assertEqual(adapter.calls, request_number)
            self.assertEqual(waiting["model_calls_since_user"], 1)
            result = execute(api, call)
            answer, state = advance(result, waiting, model_adapter=adapter)
            self.assertFalse(answer.calls)
            self.assertEqual(adapter.calls, request_number)
            self.assertEqual(state["model_calls_since_user"], 1)
            late, state = advance(result, state, model_adapter=adapter)
            self.assertFalse(late.calls)
            self.assertEqual(adapter.calls, request_number)
        self.assertEqual(adapter.seen_counters, [1, 1])

    def test_rejected_bodies_are_removed_from_live_and_restored_history(self):
        _, state = verified_state()
        decision, waiting = advance(TurnInput(kind="user", content="order #TEST1"), state)
        for content, error, status in (("sensitive-error-marker", True, "failed"),
                (json.dumps({"customer_id": "customer_b", "order_id": "#TEST1", "note": "sensitive-owner-marker"}), False, "unknown"),
                ("sensitive-invalid-marker", False, "unknown")):
            with self.subTest(status=status, error=error):
                result = ToolOutcome(id=decision.calls[0].id, content=content, error=error)
                answer, done = advance(TurnInput(kind="tools", outcomes=(result,)), waiting)
                raw_history = deepcopy(waiting["history"]) + [{"role": "tool", "id": result.id, "content": content, "error": error}]
                recovered = initial_state(raw_history)
                for candidate in (done, recovered, initial_state(done["history"])):
                    self.assertNotIn("sensitive-", json.dumps(candidate))
                    self.assertEqual(candidate["operations"][-1]["status"], status)
                    self.assertEqual(candidate["identity"], state["identity"])
                self.assertNotIn("sensitive-", answer.text)

    def test_rejected_batch_discards_even_its_valid_result_body(self):
        api, state = verified_state()
        calls = tuple(ToolAction(id=i, name=name, arguments=bind_arguments(name, args, state))
            for i,name,args in (("catalog-a", "get_product", {"product_id":"product_mug"}), ("catalog-b", "get_item", {"item_id":"item_blue"})))
        record_decision(state, Decision(calls=calls))
        valid = read_api.get_product(api, "product_mug", customer_id="customer_a", email="a@example.test")
        valid["note"] = "discard-whole-batch-marker"
        outcomes = (ToolOutcome(id="catalog-a",content=json.dumps(valid)), ToolOutcome(id="catalog-b",content="private-batch-error",error=True))
        _, done = advance(TurnInput(kind="tools",outcomes=outcomes), state)
        self.assertNotIn("discard-whole-batch-marker", json.dumps(done))
        self.assertNotIn("private-batch-error", json.dumps(done))
        self.assertEqual(initial_state(done["history"])["operations"], done["operations"])

    def test_restoration_cannot_use_future_user_text_as_verification_source(self):
        history = [{"role":"user","content":"customer_a"},
            {"role":"assistant","content":"","tool_calls":[{"id":"lookup-1","name":"lookup_customer","arguments":{"customer_id":"customer_a","email":"a@example.test"}}]},
            {"role":"tool","id":"lookup-1","content":json.dumps({"customer_id":"customer_a","email":"a@example.test"}),"error":False},
            {"role":"user","content":"a@example.test"}]
        restored = initial_state(history)
        self.assertFalse(restored["identity"]["verified"])
        self.assertIsNone(restored["identity_evidence"])
        self.assertFalse(restored["pending_calls"])

    def test_malformed_history_and_non_object_order_results_fail_closed(self):
        api, state = verified_state()
        for entry in (None, {"role": "user", "content": 42}, {"role": "tools", "tool_messages": [None]}):
            bad = deepcopy(state)
            bad["history"].append(entry)
            with self.subTest(entry=entry), self.assertRaises(InvalidState):
                clone_state(bad)
        call, waiting = advance(TurnInput(kind="user", content="my orders"), state)
        payload = json.dumps({"customer_id": "customer_a", "orders": [None]})
        answer, done = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(id=call.calls[0].id, content=payload),)), waiting)
        self.assertIn("did not match", answer.text)
        self.assertFalse(done["pending_calls"])

    def test_name_and_postal_fields_can_be_collected_across_user_turns(self):
        api, state = ReadFake(), initial_state()
        for text in ("first_name: Alice", "last_name: Example"):
            reply, state = advance(TurnInput(kind="user", content=text), state)
            self.assertFalse(reply.calls)
        restored = initial_state(state["history"])
        decision, state = advance(TurnInput(kind="user", content="postal_code: 10001"), restored)
        self.assertEqual(decision.calls[0].arguments["first_name"], "Alice")
        _, done = advance(execute(api, decision), state)
        self.assertTrue(done["identity"]["verified"])

    def test_explicit_non_hash_order_id_is_not_invented_or_dropped(self):
        api, state = verified_state()
        order = deepcopy(api.orders["#TEST1"])
        order["order_id"] = "own-order/1"
        api.orders["own-order/1"] = order
        state["customer_record"]["order_ids"].append("own-order/1")
        api.customers["customer_a"]["order_ids"].append("own-order/1")
        call, waiting = advance(TurnInput(kind="user",content="order_id: own-order/1"), state)
        self.assertEqual(call.calls[0].arguments["order_id"], "own-order/1")
        answer, _ = advance(execute(api, call), waiting)
        self.assertIn("own-order/1", answer.text)
        self.assertTrue(any(p.endswith('own-order%2F1') for _,p,_ in api.calls))

    def test_verified_identity_persists_without_resupplying_email(self):
        api, before = verified_state()
        snapshot = deepcopy(before)
        decision, waiting = advance(TurnInput(kind="user", content="List my orders"), before)
        self.assertEqual(decision.calls[0].name, "list_customer_orders")
        self.assertEqual(decision.calls[0].arguments["email"], "a@example.test")
        self.assertEqual(waiting["identity"], before["identity"])
        answer, done = advance(execute(api, decision), waiting)
        self.assertIn("#TEST1", answer.text)
        self.assertNotIn("#TEST2", answer.text)
        self.assertEqual(before, snapshot)
        self.assertEqual(clone_state(done), json.loads(json.dumps(done)))

    def test_name_postal_verification_persists_and_has_source_evidence(self):
        api = ReadFake()
        decision, state = advance(TurnInput(kind="user", content="first_name: Alice; last_name: Example; postal_code: 10001"), initial_state())
        self.assertEqual(decision.calls[0].name, "verify_customer")
        _, state = advance(execute(api, decision), state)
        decision, state = advance(TurnInput(kind="user", content="My orders"), state)
        self.assertEqual(decision.calls[0].arguments["first_name"], "Alice")
        self.assertEqual(state["identity_evidence"]["inputs"]["email"], "")
        self.assertEqual(state["identity"]["customer_id"], "customer_a")

    def test_customer_id_or_order_hint_alone_has_zero_private_calls(self):
        for text in ("customer_a", "duplicate charge for order #TEST1", "my orders"):
            decision, state = advance(TurnInput(kind="user", content=text), initial_state())
            self.assertFalse(decision.calls)
            self.assertFalse(state["identity"]["verified"])
            self.assertIn("verify", decision.text)

    def test_failed_verification_does_not_expose_approximate_accounts(self):
        decision, state = advance(TurnInput(kind="user", content="missing@example.test duplicate charge"), initial_state())
        answer, done = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(id=decision.calls[0].id, content="another customer's private record", error=True),)), state)
        self.assertFalse(done["identity"]["verified"])
        self.assertNotIn("another customer's", answer.text)
        self.assertFalse(answer.calls)

    def test_cross_customer_switch_and_roommate_order_are_blocked(self):
        _, state = verified_state()
        for text in ("customer_b", "b@example.test", "Please cancel my roommate's order #TEST2"):
            with self.subTest(text=text):
                answer, done = advance(TurnInput(kind="user", content=text), state)
                self.assertFalse(answer.calls)
                self.assertNotIn("Ben", answer.text)
                self.assertEqual(done["identity"]["customer_id"], "customer_a")

    def test_profile_or_tool_text_is_not_independent_verification(self):
        state = initial_state([{"role": "assistant", "content": "a@example.test"}])
        with self.assertRaises(InvalidAction):
            bind_arguments("lookup_customer", {"customer_id": "customer_a", "email": "a@example.test"}, state)
        legacy = initial_state()
        legacy["identity"] = {"verified": True, "customer_id": "customer_a"}
        legacy["customer_id"] = "customer_a"
        with self.assertRaises(InvalidAction):
            bind_arguments("list_products", {}, clone_state(legacy))

    def test_combined_verification_order_request_chains_only_reads(self):
        api = ReadFake()
        first, state = advance(TurnInput(kind="user", content="a@example.test order #TEST1"), initial_state())
        second, state = advance(execute(api, first), state)
        self.assertEqual(second.calls[0].name, "get_order")
        self.assertEqual(state["tool_calls_since_user"], 2)
        answer, done = advance(execute(api, second), state)
        self.assertIn("#TEST1", answer.text)
        self.assertTrue(done["identity"]["verified"])
        self.assertTrue(all(m == "GET" or (m, p) == ("POST", "/v1/customers/search") for m, p, _ in api.calls))

    def test_history_restores_identity_and_pending_owned_read_without_reissue(self):
        api, state = verified_state()
        decision, waiting = advance(TurnInput(kind="user", content="order #TEST1"), state)
        count = len(api.calls)
        restored = initial_state(waiting["history"])
        self.assertEqual(restored["identity"], waiting["identity"])
        self.assertEqual(restored["pending_calls"], waiting["pending_calls"])
        self.assertEqual(len(api.calls), count)
        result_turn = execute(api, decision)
        live, done = advance(result_turn, waiting)
        replay, recovered = advance(result_turn, restored)
        self.assertEqual(live, replay)
        self.assertEqual(done["identity"], recovered["identity"])

    def test_multi_read_results_require_complete_unique_matching_batch(self):
        api, state = verified_state()
        actions = tuple(ToolAction(id=i, name=name, arguments=bind_arguments(name, args, state))
                        for i, name, args in (("p", "get_product", {"product_id": "product_mug"}), ("i", "get_item", {"item_id": "item_blue"})))
        decision = Decision(calls=actions)
        record_decision(state, decision)
        self.assertIsNone(state["pending_call_id"])
        outcomes = execute(api, decision).outcomes
        for batch in ((), outcomes[:1], (outcomes[0], outcomes[0]), outcomes + (ToolOutcome(id="stray", content="{}"),)):
            with self.subTest(batch=batch):
                reply, done = advance(TurnInput(kind="tools", outcomes=batch), state)
                self.assertIn("ambiguous", reply.text)
                self.assertFalse(done["pending_calls"])
                recovered = initial_state(done["history"])
                self.assertEqual(recovered["operations"], done["operations"])
        answer, done = advance(TurnInput(kind="tools", outcomes=tuple(reversed(outcomes))), state)
        self.assertIn("Variants: 1", answer.text)
        self.assertTrue(all(o["status"] == "succeeded" for o in done["operations"]))

    def test_result_owner_mismatch_is_not_disclosed_and_late_results_do_not_replay(self):
        api, state = verified_state()
        decision, waiting = advance(TurnInput(kind="user", content="order #TEST1"), state)
        bad = deepcopy(api.orders["#TEST2"])
        bad["order_id"] = "#TEST1"
        answer, done = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(id=decision.calls[0].id, content=json.dumps(bad)),)), waiting)
        self.assertIn("did not match", answer.text)
        self.assertNotIn("customer_b", answer.text)
        late, later = advance(execute(api, decision), done)
        self.assertFalse(late.calls)
        self.assertEqual(later["identity"]["customer_id"], "customer_a")

    def test_product_counts_and_original_catalog_prices_are_distinct(self):
        api, state = verified_state()
        api.products["product_mug"]["items"][0]["price"] = 20.0
        call, state = advance(TurnInput(kind="user", content="product_id: product_mug"), state)
        answer, state = advance(execute(api, call), state)
        self.assertIn("Variants: 1; available variants: 1", answer.text)
        self.assertIn("20.0", answer.text)
        call, state = advance(TurnInput(kind="user", content="order #TEST1"), state)
        answer, _ = advance(execute(api, call), state)
        self.assertIn("12.5", answer.text)
        self.assertIn("dates and delivery estimates are unknown", answer.text)

    def test_ambiguous_query_clarifies_and_model_failures_fall_back_without_calls(self):
        _, state = verified_state()
        class Broken:
            def decide(self, state):
                raise RuntimeError("secret provider detail")
        answer, _ = advance(TurnInput(kind="user", content="the thing I ordered last week"), state, model_adapter=Broken())
        self.assertFalse(answer.calls)
        self.assertNotIn("secret", answer.text)
        self.assertIn("specify", answer.text)

    def test_read_budget_and_reused_ids_are_enforced_before_emit(self):
        _, state = verified_state()
        args = bind_arguments("list_products", {}, state)
        state["tool_calls_since_user"] = 12
        with self.assertRaises(InvalidAction):
            record_decision(state, Decision(calls=(ToolAction(id="budget", name="list_products", arguments=args),)))
        state["tool_calls_since_user"] = 0
        with self.assertRaises(InvalidAction):
            record_decision(state, Decision(calls=(ToolAction(id=state["operations"][0]["call_id"], name="list_products", arguments=args),)))

    def test_forged_evidence_and_pending_customer_scope_are_rejected(self):
        _, state = verified_state()
        bad = deepcopy(state)
        bad["identity_evidence"]["inputs"]["email"] = "b@example.test"
        with self.assertRaises(InvalidState):
            clone_state(bad)
        call, waiting = advance(TurnInput(kind="user", content="order #TEST1"), state)
        waiting["pending_calls"][call.calls[0].id]["arguments"]["customer_id"] = "customer_b"
        with self.assertRaises(InvalidState):
            clone_state(waiting)
