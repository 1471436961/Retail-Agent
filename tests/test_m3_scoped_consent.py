"""M3.3 on actual presentation, user reducer, accepted reads and recovery."""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from fakes import FakeClientAPI
from test_m3_proposals import accept_read, agree, specification, verified_state
from support_agent.proposals import (InvalidProposal, check_confirmation, confirmation_matches,
                                     present_proposal, present_proposals, record_ack, render_proposal_set)
from support_agent.protocol import InvalidAction, TurnInput, decision_from_candidate
from support_agent.state import InvalidState, SCHEMA_VERSION, clone_state, initial_state
from support_agent.turns import advance


def scoped(*actions, **fixture):
    state, api = verified_state(**fixture)
    specs = [specification(a) for a in actions or ("shipping_address", "payment_method")]
    decision, state = present_proposals(state, specs)
    return decision, state, specs, api


def explode_model():
    return type("ForbiddenModel", (), {"decide": lambda self, state: (_ for _ in ()).throw(
        AssertionError("Scoped consent must not call a model"))})()


def record_for(state, version, spec):
    """Identify the published version and exact scope, independent of position."""
    records = [p for p in state["proposals"] if p["version"] == version
               and p["spec"]["action"] == spec["action"] and p["spec"]["target"] == spec["target"]]
    if len(records) != 1:
        raise AssertionError("Expected one proposal with the specified version and scope")
    return records[0]


class ScopedConsentTests(unittest.TestCase):
    def test_recap_contains_each_full_scope_quote_and_one_question(self):
        decision, state, specs, api = scoped()
        self.assertEqual(decision.text, render_proposal_set(specs))
        for text in ("Operation 1:", "Operation 2:", "90002", "14.5", "card_other", "12.5 to card_a", "#TEST1"):
            self.assertIn(text, decision.text)
        self.assertEqual(decision.text.count("?"), 1)
        self.assertFalse(decision.calls)
        self.assertEqual([p["version"] for p in state["proposals"]], [1, 2])
        self.assertEqual(api.calls[-1][0], "GET")

    def test_whole_consent_matches_each_exact_complete_scope(self):
        _, state, specs, api = scoped()
        before = deepcopy(api.calls)
        decision, confirmed = advance(TurnInput(kind="user", content="yes"), state, model_adapter=explode_model())
        self.assertFalse(decision.calls)
        for version, spec in enumerate(specs, 1):
            self.assertTrue(confirmation_matches(confirmed, version, spec))
        self.assertIn("1, 2", decision.text)
        self.assertEqual(api.calls, before)

    def test_partial_numbered_assent_never_confirms_other_operation(self):
        for text in ("confirm only operation 1", "只确认第1项", "confirm only the order address", "只确认订单地址"):
            _, state, specs, _ = scoped()
            with self.subTest(text=text):
                decision, confirmed = advance(TurnInput(kind="user", content=text), state, model_adapter=explode_model())
                self.assertTrue(confirmation_matches(confirmed, 1, specs[0]))
                self.assertEqual(check_confirmation(confirmed, 2, specs[1])["code"], "scope_not_confirmed")
                self.assertEqual(confirmed["proposals"][1]["response"]["kind"], "deferred")
                self.assertIn("only for operation(s) 1.", decision.text)

    def test_multiple_numbered_scopes_preserve_display_order(self):
        for text in ("confirm operations 1 and 3", "确认第1项和第3项"):
            _, state, specs, _ = scoped("shipping_address", "payment_method", "default_shipping_address")
            _, confirmed = agree(state, text)
            self.assertEqual([confirmation_matches(confirmed, i, s) for i, s in enumerate(specs, 1)], [True, False, True])
            self.assertEqual([e["version"] for e in confirmed["history"][-1]["proposal_set_ack"]], [1, 3])

    def test_explicit_confirmation_and_withdrawal_have_disjoint_effects(self):
        for text in ("confirm operation 1; withdraw operation 2", "确认第1项；撤回第2项"):
            _, state, specs, _ = scoped()
            _, confirmed = agree(state, text)
            self.assertTrue(confirmation_matches(confirmed, 1, specs[0]))
            self.assertFalse(confirmation_matches(confirmed, 2, specs[1]))
            self.assertEqual(confirmed["proposals"][1]["status"], "withdrawn")

    def test_confirmation_and_payment_change_preserve_only_unchanged_scope(self):
        _, state, specs, _ = scoped()
        _, revised = agree(state, "confirm operation 1; change operation 2 to card_a")
        self.assertTrue(confirmation_matches(revised, 1, specs[0]))
        self.assertFalse(confirmation_matches(revised, 2, specs[1]))
        self.assertEqual(revised["proposals"][1]["response"]["kind"], "amend")
        self.assertEqual(revised["proposals"][1]["spec"]["parameters"]["payment_method_id"], "card_other")

    def test_withdrawal_clears_previously_confirmed_evidence(self):
        for text in ("withdraw all", "do not proceed", "撤回全部", "什么都不改"):
            _, state, specs, _ = scoped()
            _, state = agree(state)
            _, withdrawn = advance(TurnInput(kind="user", content=text), state, model_adapter=explode_model())
            self.assertEqual([p["status"] for p in withdrawn["proposals"]], ["withdrawn", "withdrawn"])
            self.assertTrue(all(p["confirmation"] is None for p in withdrawn["proposals"]))
            self.assertFalse(confirmation_matches(withdrawn, 1, specs[0]))
            _, later = agree(withdrawn)
            self.assertFalse(confirmation_matches(later, 1, specs[0]))

    def test_scoped_withdrawal_does_not_revoke_other_explicit_consent(self):
        _, state, specs, _ = scoped()
        _, confirmed = agree(state)
        evidence = deepcopy(confirmed["proposals"][0]["confirmation"])
        _, withdrawn = agree(confirmed, "withdraw operation 2")
        self.assertEqual(withdrawn["proposals"][0]["confirmation"], evidence)
        self.assertTrue(confirmation_matches(withdrawn, 1, specs[0]))
        self.assertFalse(confirmation_matches(withdrawn, 2, specs[1]))

    def test_repeated_yes_after_partial_ack_does_not_expand_consent(self):
        _, state, specs, _ = scoped()
        _, partial = agree(state, "confirm only operation 1")
        evidence = deepcopy(partial["proposals"][0]["confirmation"])
        _, repeated = agree(partial)
        self.assertEqual(repeated["proposals"][0]["confirmation"], evidence)
        self.assertFalse(confirmation_matches(repeated, 2, specs[1]))
        self.assertEqual([e["version"] for e in repeated["history"][-1]["proposal_set_ack"]], [1])

    def test_later_scoped_yes_requires_another_complete_presentation(self):
        _, state, specs, _ = scoped()
        _, state = agree(state, "confirm only operation 1")
        _, later = agree(state, "confirm operation 2")
        self.assertFalse(confirmation_matches(later, 2, specs[1]))
        _, recapped = present_proposals(later, [specs[1]])
        _, recapped = agree(recapped)
        self.assertTrue(confirmation_matches(recapped, 3, specs[1]))

    def test_intervening_question_prevents_scoped_confirmation(self):
        _, state, specs, _ = scoped()
        state["history"].append({"role": "assistant", "content": "Is your email correct?"})
        _, replied = agree(state, "confirm operation 1")
        self.assertFalse(confirmation_matches(replied, 1, specs[0]))
        self.assertEqual(replied["proposals"][0]["response"]["kind"], "unresolved")

    def test_condition_is_not_consent_even_if_price_already_satisfies_it(self):
        for text in ("yes if the difference is negative", "yes if cheaper", "如果差价是负数就确认", "先改地址再换支付方式"):
            _, state, specs, _ = scoped("modify_items", "shipping_address")
            with self.subTest(text=text):
                decision, conditional = advance(TurnInput(kind="user", content=text), state, model_adapter=explode_model())
                self.assertFalse(decision.calls)
                self.assertIn("condition is unresolved", decision.text)
                self.assertEqual([p["response"]["kind"] for p in conditional["proposals"]], ["condition", "condition"])
                self.assertFalse(confirmation_matches(conditional, 1, specs[0]))

    def test_explicit_independent_condition_does_not_authorize_its_branch(self):
        _, state, specs, _ = scoped()
        _, reply = agree(state, "confirm operation 1; confirm operation 2 if the gift card is sufficient")
        self.assertTrue(confirmation_matches(reply, 1, specs[0]))
        self.assertFalse(confirmation_matches(reply, 2, specs[1]))
        self.assertEqual(reply["proposals"][1]["response"]["kind"], "condition")

    def test_resolved_branch_requires_new_version_and_fresh_user_confirmation(self):
        _, state, specs, _ = scoped("modify_items")
        _, state = agree(state, "if cheaper change it, otherwise keep it")
        changed = deepcopy(specs[0]); changed["amount"]["value"] = -2
        _, recapped = present_proposals(state, [changed])
        self.assertFalse(confirmation_matches(recapped, 1, specs[0]))
        self.assertFalse(confirmation_matches(recapped, 2, changed))
        _, recapped = agree(recapped)
        self.assertTrue(confirmation_matches(recapped, 2, changed))

    def test_item_subset_does_not_authorize_splitting_one_shot_operation(self):
        _, state, specs, _ = scoped("exchange", status="delivered", item_copies=2)
        specs[0]["parameters"]["replacements"] *= 2
        _, state = present_proposals(state, specs)
        _, narrowed = agree(state, "只换其中一件")
        self.assertFalse(confirmation_matches(narrowed, 2, specs[0]))
        self.assertEqual(len(narrowed["proposals"][-1]["spec"]["parameters"]["replacements"]), 2)
        new = deepcopy(specs[0]); new["parameters"]["replacements"].pop(); new["amount"]["value"] = -1.125
        _, narrowed = present_proposals(narrowed, [new])
        self.assertFalse(confirmation_matches(narrowed, 3, new))
        _, narrowed = agree(narrowed)
        self.assertTrue(confirmation_matches(narrowed, 3, new))

    def test_switch_from_exchange_to_unpriced_return_cannot_keep_exchange_consent(self):
        _, state, specs, _ = scoped("exchange", status="delivered")
        _, state = agree(state)
        decision, state = advance(TurnInput(kind="user", content="什么都不换，改为退回水瓶"), state, model_adapter=explode_model())
        self.assertFalse(decision.calls)
        self.assertFalse(confirmation_matches(state, 1, specs[0]))
        returned = {"action": "return", "target": deepcopy(specs[0]["target"]),
                    "parameters": {"item_ids": ["item_blue"], "refund_payment_method_id": "card_a"},
                    "amount": {"kind": "refund_estimate", "value": 12.5}}
        with self.assertRaises(InvalidProposal): present_proposals(state, [returned])
        self.assertFalse(confirmation_matches(state, 1, specs[0]))

    def test_scoped_presentation_keeps_identity_pending_handoff_and_locked_state_gates(self):
        state, _ = verified_state()
        for mutate in (lambda s: s["handoff"].update(status="accepted"), lambda s: s.update(identity_evidence=None)):
            blocked = deepcopy(state); mutate(blocked)
            with self.assertRaises((InvalidState, InvalidProposal)): present_proposals(blocked, [specification()])
        for status, action in (("pending (items modified)", "payment_method"), ("return requested", "exchange"),
                               ("exchange requested", "exchange"), ("processed", "shipping_address")):
            blocked, _ = verified_state(status=status)
            with self.subTest(status=status), self.assertRaises(InvalidProposal): present_proposals(blocked, [specification(action)])
        decision, pending = agree(state, "Read order #TEST1")
        self.assertTrue(decision.calls)
        with self.assertRaises(InvalidProposal): present_proposals(pending, [specification()])

    def test_addition_blocks_old_list_until_complete_recap_and_reply(self):
        _, state, specs, _ = scoped("modify_items", item_copies=2)
        _, state = agree(state)
        _, changed = advance(TurnInput(kind="user", content="yes, but add another item_blue"), state, model_adapter=explode_model())
        self.assertFalse(confirmation_matches(changed, 1, specs[0]))
        new = deepcopy(specs[0]); new["parameters"]["replacements"] *= 2; new["amount"]["value"] = -2.25
        _, changed = present_proposals(changed, [new])
        self.assertIn("entire modification list", changed["history"][-1]["content"])
        self.assertEqual(changed["history"][-1]["content"].count("Replace item_blue"), 2)
        self.assertFalse(confirmation_matches(changed, 2, new))
        _, changed = agree(changed)
        self.assertTrue(confirmation_matches(changed, 2, new))

    def test_changed_payment_and_quote_cannot_reuse_old_confirmation(self):
        for field in ("method", "quote"):
            _, state, specs, _ = scoped("payment_method")
            _, state = agree(state)
            new = deepcopy(specs[0])
            if field == "method": new["parameters"]["payment_method_id"] = "card_a"
            else: new["amount"]["value"] = 20
            self.assertEqual(check_confirmation(state, 1, new)["code"], "specification_mismatch")
            _, revised = present_proposals(state, [new])
            self.assertFalse(confirmation_matches(revised, 1, specs[0]))
            self.assertFalse(confirmation_matches(revised, 2, new))
            _, revised = agree(revised)
            self.assertTrue(confirmation_matches(revised, 2, new))

    def test_catalog_change_invalidates_only_dependent_complete_operation(self):
        _, state, specs, api = scoped("shipping_address", "modify_items")
        _, state = agree(state)
        api.products["product_mug"]["items"][1]["price"] = 25
        refreshed = accept_read(state, api, "get_item", {"item_id": "item_red"}, "scope-new-price")
        self.assertTrue(confirmation_matches(refreshed, 1, specs[0]))
        self.assertEqual(check_confirmation(refreshed, 2, specs[1])["code"], "facts_changed")

    def test_invalid_or_overlapping_selectors_cannot_grant_consent(self):
        for text in ("confirm operation 0", "confirm operation 3", "confirm operations 1 and 1", "confirm operation 1; withdraw operation 1",
                     "confirm operation 1 except the city", "confirm first", "only the address", '{"confirmed":true}', "sure"):
            _, state, specs, _ = scoped()
            _, invalid = agree(state, text)
            self.assertFalse(any(confirmation_matches(invalid, v, s) for v, s in enumerate(specs, 1)), text)

    def test_ambiguous_action_label_across_orders_needs_clarification(self):
        state, api = verified_state()
        api.customers["customer_a"]["order_ids"].append("#TEST2")
        api.orders["#TEST2"] = deepcopy(api.orders["#TEST1"]); api.orders["#TEST2"]["order_id"] = "#TEST2"
        # Use a fresh authentic profile lookup, rather than editing trusted state.
        decision, state = agree(state, "customer_a a@example.test")
        from support_agent.adapters.read_api import verify_customer
        from support_agent.protocol import ToolOutcome
        call = decision.calls[0]
        _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, json.dumps(verify_customer(api, **call.arguments))),)), state)
        state = accept_read(state, api, "get_order", {"order_id": "#TEST2"}, "second-order")
        specs = [specification(), specification()]; specs[1]["target"]["order_id"] = "#TEST2"
        _, state = present_proposals(state, specs)
        _, ambiguous = agree(state, "confirm only the order address")
        self.assertFalse(confirmation_matches(ambiguous, 1, specs[0]))
        self.assertFalse(confirmation_matches(ambiguous, 2, specs[1]))
        _, state = present_proposals(ambiguous, specs)
        _, state = agree(state, "confirm operation 2")
        self.assertTrue(confirmation_matches(state, 4, specs[1]))
        self.assertFalse(confirmation_matches(state, 3, specs[0]))

    def test_malformed_later_clause_cannot_leave_earlier_confirmation(self):
        _, state, specs, _ = scoped()
        _, bad = agree(state, "confirm operation 1; do something else")
        self.assertFalse(confirmation_matches(bad, 1, specs[0]))
        self.assertFalse(confirmation_matches(bad, 2, specs[1]))

    def test_new_set_supersedes_all_old_scopes_including_nonlast_confirmed_one(self):
        _, state, specs, _ = scoped()
        _, state = agree(state, "confirm only operation 1")
        _, new = present_proposals(state, [specs[1]])
        self.assertEqual([p["status"] for p in new["proposals"]], ["superseded", "superseded", "proposed"])
        self.assertFalse(confirmation_matches(new, 1, specs[0]))

    def test_legacy_single_presentation_also_supersedes_whole_current_set(self):
        _, state, specs, _ = scoped()
        _, state = agree(state)
        _, revised = present_proposal(state, specs[1])
        self.assertEqual([p["status"] for p in revised["proposals"]], ["superseded", "superseded", "proposed"])
        _, revised = agree(revised)
        self.assertTrue(confirmation_matches(revised, 3, specs[1]))

    def test_same_confirmed_set_and_equal_numbers_preserve_original_evidence(self):
        state, _ = verified_state()
        specs = [specification(), specification("payment_method")]
        specs[1]["amount"]["value"] = 14
        _, state = present_proposals(state, specs)
        _, state = agree(state)
        original = deepcopy(state["proposals"])
        same = deepcopy(specs); same[1]["amount"]["value"] = 14.0
        _, repeated = present_proposals(state, same)
        self.assertEqual(repeated["proposals"], original)
        self.assertIn("proposal_set_ack", repeated["history"][-1])

    def test_revised_second_scope_retains_first_original_consent_without_reasking(self):
        _, state, specs, _ = scoped()
        _, state = agree(state)
        original = deepcopy(state["proposals"][0]["confirmation"])
        reply, state = advance(TurnInput(kind="user", content="change operation 2 to card_a"), state, model_adapter=explode_model())
        self.assertFalse(reply.calls)
        self.assertIn("new complete list, quote and recap", reply.text)
        revised_scope = record_for(state, 2, specs[1])
        self.assertEqual(revised_scope["status"], "needs_review")
        self.assertIsNone(revised_scope["confirmation"])
        self.assertEqual(revised_scope["response"], {"kind": "amend", "history_index": len(state["history"]) - 2})
        self.assertEqual(revised_scope["spec"], specs[1])
        self.assertEqual(check_confirmation(state, 2, specs[1])["code"], "proposal_amended")
        self.assertTrue(confirmation_matches(state, 1, specs[0]))
        new = deepcopy(specs); new[1]["parameters"]["payment_method_id"] = "card_a"
        decision, state = present_proposals(state, new)
        self.assertIn("Existing confirmation", decision.text)
        self.assertTrue(confirmation_matches(state, 3, new[0]))
        self.assertEqual(state["proposals"][2]["confirmation"], original)
        self.assertEqual(state["proposals"][2]["reuse_version"], 1)
        self.assertFalse(confirmation_matches(state, 4, new[1]))
        _, state = agree(state)
        self.assertTrue(confirmation_matches(state, 4, new[1]))
        self.assertEqual(state["proposals"][2]["confirmation"], original)

    def test_fact_change_or_withdrawal_prevents_retaining_same_scope(self):
        for mode in ("facts", "withdraw"):
            _, state, specs, api = scoped("modify_items", "shipping_address")
            _, state = agree(state)
            unaffected_evidence = deepcopy(record_for(state, 2, specs[1])["confirmation"])
            if mode == "facts":
                api.products["product_mug"]["items"][1]["price"] = 40
                state = accept_read(state, api, "get_item", {"item_id": "item_red"}, "retention-price")
            else:
                _, state = agree(state, "withdraw operation 1")
            _, revised = present_proposals(state, specs)
            affected = record_for(revised, 3, specs[0])
            unaffected = record_for(revised, 4, specs[1])
            self.assertIsNone(affected["reuse_version"])
            self.assertFalse(confirmation_matches(revised, 3, specs[0]))
            self.assertEqual(unaffected["reuse_version"], 2)
            self.assertEqual(unaffected["confirmation"], unaffected_evidence)
            self.assertTrue(confirmation_matches(revised, 4, specs[1]))

    def test_expanded_item_list_retains_unrelated_scope_and_requires_new_item_consent(self):
        _, state, specs, api = scoped("shipping_address", "modify_items", item_copies=2)
        _, state = agree(state)
        original = deepcopy(record_for(state, 1, specs[0])["confirmation"])
        reads = deepcopy(api.calls)
        reply, amended = advance(TurnInput(kind="user", content="change operation 2 to add another item_blue"),
                                 state, model_adapter=explode_model())
        self.assertFalse(reply.calls)
        self.assertTrue(confirmation_matches(amended, 1, specs[0]))
        self.assertEqual(check_confirmation(amended, 2, specs[1])["code"], "proposal_amended")
        expanded = deepcopy(specs)
        expanded[1]["parameters"]["replacements"] *= 2
        expanded[1]["amount"]["value"] = -2.25
        recap, revised = present_proposals(amended, expanded)
        self.assertEqual(recap.text.count("Replace item_blue with item_red"), 2)
        self.assertIn("entire modification list", recap.text)
        self.assertEqual(record_for(revised, 3, expanded[0])["confirmation"], original)
        self.assertEqual(record_for(revised, 3, expanded[0])["reuse_version"], 1)
        self.assertTrue(confirmation_matches(revised, 3, expanded[0]))
        self.assertIsNone(record_for(revised, 4, expanded[1])["reuse_version"])
        self.assertEqual(check_confirmation(revised, 4, expanded[1])["code"], "confirmation_required")
        self.assertEqual(check_confirmation(revised, 2, specs[1])["code"], "version_mismatch")
        self.assertEqual(check_confirmation(revised, 4, specs[1])["code"], "specification_mismatch")
        _, confirmed = advance(TurnInput(kind="user", content="confirm operation 2"), revised, model_adapter=explode_model())
        self.assertTrue(confirmation_matches(confirmed, 4, expanded[1]))
        self.assertEqual(record_for(confirmed, 3, expanded[0])["confirmation"], original)
        self.assertEqual(api.calls, reads)
        with patch.object(FakeClientAPI, "request", side_effect=AssertionError("No recovery API")):
            self.assertEqual(initial_state(confirmed["history"])["proposals"], confirmed["proposals"])

    def test_condition_and_amendment_combination_keeps_each_scope_unconfirmed(self):
        for text in ("change operation 1 to another address; confirm operation 2 if the gift card is sufficient",
                     "confirm operation 2 if the gift card is sufficient; change operation 1 to another address"):
            _, state, specs, _ = scoped()
            _, state = agree(state)
            reply, blocked = advance(TurnInput(kind="user", content=text), state, model_adapter=explode_model())
            self.assertFalse(reply.calls)
            self.assertIn("condition is unresolved", reply.text)
            user_index = len(blocked["history"]) - 2
            for version, spec, kind, code in ((1, specs[0], "amend", "proposal_amended"),
                                               (2, specs[1], "condition", "condition_unresolved")):
                record = record_for(blocked, version, spec)
                self.assertEqual(record["status"], "needs_review")
                self.assertIsNone(record["confirmation"])
                self.assertEqual(record["response"], {"kind": kind, "history_index": user_index})
                self.assertEqual(record["spec"], spec)
                self.assertEqual(check_confirmation(blocked, version, spec)["code"], code)
            self.assertEqual(initial_state(blocked["history"])["proposals"], blocked["proposals"])

    def test_new_scope_reply_preserves_retained_consent_unless_user_explicitly_excludes_it(self):
        for text, retained in (("confirm operation 2", True), ("confirm only operation 2", False)):
            _, state, specs, _ = scoped()
            _, state = agree(state)
            _, state = agree(state, "change operation 2 to card_a")
            specs[1]["parameters"]["payment_method_id"] = "card_a"
            _, state = present_proposals(state, specs)
            _, state = agree(state, text)
            self.assertEqual(confirmation_matches(state, 3, specs[0]), retained)
            self.assertTrue(confirmation_matches(state, 4, specs[1]))

    def test_set_validation_is_atomic_and_does_not_mutate_inputs_or_call_api(self):
        state, api = verified_state()
        snapshot, reads = deepcopy(state), deepcopy(api.calls)
        specs = [specification(), specification("payment_method")]
        specs[1]["parameters"]["payment_method_id"] = "not_saved"
        original = deepcopy(specs)
        with self.assertRaises(InvalidProposal): present_proposals(state, specs)
        self.assertEqual(state, snapshot); self.assertEqual(specs, original); self.assertEqual(api.calls, reads)

    def test_duplicate_scopes_conflicting_cancellation_and_bad_set_types_are_rejected(self):
        state, _ = verified_state()
        valid = [specification(), specification("payment_method")]
        decision, accepted = present_proposals(state, valid)
        self.assertFalse(decision.calls)
        self.assertEqual([p["spec"] for p in accepted["proposals"]], valid)
        # Construction uses InvalidProposal messages, not confirmation-result codes.
        for specs, reason in (([], "nonempty list"), (None, "nonempty list"), ((specification(),), "nonempty list"),
                              ([specification(), specification()], "Duplicate operation scopes"),
                              ([specification("cancel"), specification()], "Resolve cancellation versus"),
                              ([specification(), {"confirmed": True}], "Incomplete or unsupported proposal fields")):
            snapshot = deepcopy(state)
            with self.subTest(reason=reason), self.assertRaisesRegex(InvalidProposal, reason):
                present_proposals(state, specs)
            self.assertEqual(state, snapshot)

    def test_model_has_no_scoped_confirmation_or_presentation_surface(self):
        for candidate in ({"type": "proposal_set", "specs": [specification()]},
                          {"type": "reply", "text": "confirm operation 1", "confirmed": True},
                          {"type": "tool", "name": "present_proposals", "arguments": {}}):
            with self.assertRaises(InvalidAction): decision_from_candidate(candidate, call_id="bad")
        _, state, specs, _ = scoped()
        text = "confirm operation 1"
        _, user_confirmed = advance(TurnInput(kind="user", content=text), state, model_adapter=explode_model())
        self.assertTrue(confirmation_matches(user_confirmed, 1, specs[0]))
        self.assertFalse(confirmation_matches(user_confirmed, 2, specs[1]))
        evidence = record_for(user_confirmed, 1, specs[0])["confirmation"]
        self.assertEqual(user_confirmed["history"][evidence["history_index"]], {"role": "user", "content": text})
        assistant_history = deepcopy(state["history"]) + [{"role": "assistant", "content": text}]
        restored = initial_state(assistant_history)
        self.assertFalse(confirmation_matches(restored, 1, specs[0]))

        class FakeModel:
            calls = 0
            def decide(self, observed):
                self.calls += 1
                return decision_from_candidate({"type": "reply", "text": text}, call_id="model-reply")

        model = FakeModel()
        reply, model_replied = advance(TurnInput(kind="user", content="maybe"), state, model_adapter=model)
        self.assertEqual(model.calls, 1)
        self.assertEqual(reply.text, text)
        self.assertFalse(reply.calls)
        self.assertEqual(model_replied["history"][-1], {"role": "assistant", "content": text})
        self.assertFalse(any(confirmation_matches(model_replied, v, s) for v, s in enumerate(specs, 1)))


class ScopedRecoveryTests(unittest.TestCase):
    def test_fresh_scoped_proposals_report_confirmation_required_for_each_operation(self):
        _, state, specs, _ = scoped()
        for version, spec in enumerate(specs, 1):
            outcome = check_confirmation(state, version, spec)
            self.assertEqual(outcome["decision"], "needs_information")
            self.assertEqual(outcome["code"], "confirmation_required")
            self.assertFalse(outcome["details"]["confirmation_matches"])
            record = record_for(state, version, spec)
            self.assertEqual(record["status"], "proposed")
            self.assertIsNone(record["response"])
            self.assertIsNone(record["confirmation"])

    def test_scoped_outcomes_explain_withdrawal_conditions_changes_and_ambiguity(self):
        for text, code, decision in (("withdraw all", "proposal_withdrawn", "deny"),
                                     ("yes if cheaper", "condition_unresolved", "needs_information"),
                                     ("add one item", "proposal_amended", "needs_information"),
                                     ("maybe", "response_unresolved", "needs_information")):
            _, state, specs, _ = scoped()
            _, state = agree(state, text)
            outcome = check_confirmation(state, 1, specs[0])
            self.assertEqual(outcome["code"], code)
            self.assertEqual(outcome["decision"], decision)
            self.assertFalse(outcome["details"]["confirmation_matches"])

    def test_retained_consent_source_replays_and_cannot_be_forged(self):
        _, state, specs, _ = scoped()
        _, state = agree(state)
        original = deepcopy(state["proposals"][0]["confirmation"])
        _, state = agree(state, "change operation 2 to card_a")
        specs[1]["parameters"]["payment_method_id"] = "card_a"
        _, state = present_proposals(state, specs)
        self.assertEqual(initial_state(state["history"])["proposals"], state["proposals"])
        self.assertEqual(state["proposals"][2]["confirmation"], original)
        for reference in (True, 2, 999):
            damaged = deepcopy(state); damaged["history"][-1]["proposal_set"][0]["reuse_version"] = reference
            with self.subTest(reference=reference), self.assertRaises(InvalidState): clone_state(damaged)
        damaged = deepcopy(state); damaged["history"][original["history_index"]]["content"] = "no"
        with self.assertRaises(InvalidState): clone_state(damaged)
    def test_clone_and_prefix_recovery_match_for_all_response_categories_without_api(self):
        for text in ("yes", "confirm operation 1", "withdraw all", "confirm operation 1; change operation 2 to card_a",
                     "if cheaper do it", "add another item", "Read order #TEST1"):
            _, state, _, _ = scoped()
            _, state = agree(state, text)
            with patch.object(FakeClientAPI, "request", side_effect=AssertionError("No recovery API")):
                cloned = clone_state(state); restored = initial_state(state["history"])
            self.assertEqual(cloned["proposals"], restored["proposals"], text)

    def test_tampered_scope_response_and_cross_version_consent_are_rejected(self):
        _, state, _, _ = scoped()
        _, state = agree(state, "confirm only operation 1")
        for field, value in (("status", "confirmed"), ("response", {"kind": "confirm", "history_index": 0}),
                             ("set_index", 0), ("confirmation", deepcopy(state["proposals"][0]["confirmation"]))):
            damaged = deepcopy(state); damaged["proposals"][1][field] = value
            with self.subTest(field=field), self.assertRaises(InvalidState): clone_state(damaged)

    def test_set_metadata_and_recap_order_cannot_be_forged(self):
        _, state, _, _ = scoped()
        for mutate in (lambda e: e["proposal_set"].reverse(), lambda e: e["proposal_set"][0].update(version=True),
                       lambda e: e["proposal_set"][0].update(request_index=999), lambda e: e.update(role="user"),
                       lambda e: e.update(content=e["content"].replace("14.5", "999")),
                       lambda e: e["proposal_set"][1]["facts"]["customer"].update(email="forged@example.test")):
            damaged = deepcopy(state); mutate(damaged["history"][-1])
            with self.assertRaises(InvalidState): clone_state(damaged)

    def test_ack_cannot_create_expand_or_retype_user_consent(self):
        _, state, _, _ = scoped()
        _, state = agree(state, "confirm operation 1")
        for mutate in (lambda e: e["proposal_set_ack"][0].update(version=2),
                       lambda e: e["proposal_set_ack"][0].update(confirmation_index=True),
                       lambda e: e["proposal_set_ack"].append(deepcopy(e["proposal_set_ack"][0])),
                       lambda e: e.update(proposal_ack=e["proposal_set_ack"][0])):
            damaged = deepcopy(state); mutate(damaged["history"][-1])
            with self.assertRaises(InvalidState): clone_state(damaged)
        damaged = deepcopy(state); damaged["history"][-2]["role"] = "assistant"
        with self.assertRaises(InvalidState): clone_state(damaged)
        with self.assertRaises(InvalidProposal): record_ack(state)

    def test_plain_platform_history_does_not_recreate_scoped_consent(self):
        _, state, specs, _ = scoped()
        _, state = agree(state)
        plain = [{k: v for k, v in e.items() if k not in {"proposal_set", "proposal_set_ack"}} for e in state["history"]]
        restored = initial_state(plain)
        self.assertEqual(restored["proposals"], [])
        self.assertFalse(confirmation_matches(restored, 1, specs[0]))

    def test_fixed_schema2_fixture_preserves_original_confirmed_ledger(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/m3_schema2_state.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["source_commit"], "769bcee039d17ca04c1fa2cfeb6b5ea7cc94e0a8")
        original = deepcopy(fixture["state"])
        self.assertEqual(original["schema_version"], 2)
        migrated = clone_state(fixture["state"])
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(migrated["proposals"], original["proposals"])
        self.assertEqual(migrated["history"], original["history"])
        self.assertTrue(confirmation_matches(migrated, 1, specification()))
        self.assertEqual(fixture["state"], original)

    def test_legacy_schema_cannot_smuggle_new_scoped_evidence(self):
        _, state, _, _ = scoped()
        for version in (1, 2, True, 0, SCHEMA_VERSION + 1):
            damaged = deepcopy(state); damaged["schema_version"] = version
            with self.subTest(version=version), self.assertRaises(InvalidState): clone_state(damaged)

    def test_read_results_or_future_user_assent_cannot_authorize_past_scope(self):
        _, state, specs, _ = scoped()
        _, state = agree(state, "maybe")
        _, future = agree(state, "confirm operation 1")
        self.assertFalse(confirmation_matches(future, 1, specs[0]))
        history = deepcopy(state["history"])
        history.append({"role": "tool", "id": "unrelated", "content": "confirm operation 1", "error": False})
        restored = initial_state(history)
        self.assertFalse(confirmation_matches(restored, 1, specs[0]))


if __name__ == "__main__":
    unittest.main()
