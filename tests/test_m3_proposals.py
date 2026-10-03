"""M3.2 consent and recovery on real reducer paths, with read-only fake APIs."""
import json
import sys
import os
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from fakes import FakeClientAPI
from support_agent.adapters.read_api import get_item, get_order, get_product, verify_customer
from support_agent.proposals import (ACK, InvalidProposal, check_confirmation, confirmation_matches, normalize_spec,
                                     present_proposal, render_proposal)
from support_agent.protocol import Decision, InvalidAction, ToolAction, ToolOutcome, TurnInput, decision_from_candidate
from support_agent.read_session import bind_arguments, record_decision
from support_agent.state import InvalidState, SCHEMA_VERSION, clone_state, initial_state
from support_agent.turns import advance


def address():
    return {"address_line_1": "2 Test St", "address_line_2": None, "city": "Testville", "region": "CA",
            "country": "US", "postal_code": "90002"}


def specification(action="shipping_address"):
    target = {"customer_id": "customer_a", "order_id": "#TEST1"}
    if action == "default_shipping_address":
        target.pop("order_id")
    if action in {"shipping_address", "default_shipping_address"}:
        params, amount = address(), {"kind": "not_applicable"}
    elif action == "cancel":
        params = {"reason": "ordered by mistake"}
        amount = {"kind": "per_charge_refunds", "rows": [
            {"transaction_type": "payment", "amount": 12.5, "payment_method_id": "card_a"},
            {"transaction_type": "payment", "amount": 2, "payment_method_id": "card_a"}]}
    elif action == "payment_method":
        params, amount = {"payment_method_id": "card_other"}, {"kind": "order_total", "value": 14.5,
                        "refund_rows": specification("cancel")["amount"]["rows"]}
    else:
        params = {"replacements": [{"existing_item_id": "item_blue", "replacement_item_id": "item_red"}],
                  "payment_method_id": "card_other"}
        amount = {"kind": "price_difference", "value": -1.125}
    return {"action": action, "target": target, "parameters": params, "amount": amount}


def accept_read(state, api, name, selectors, call_id):
    call = ToolAction(call_id, name, bind_arguments(name, selectors, state))
    record_decision(state, Decision(calls=(call,)))
    body = {"get_product": get_product, "get_item": get_item, "get_order": get_order}[name](api, **call.arguments)
    _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, json.dumps(body)),)), state)
    if state["operations"][-1]["status"] != "succeeded":
        raise AssertionError("Fixture read must be accepted by the real reducer")
    return state


def verified_state(*, with_order=True, with_catalog=True, status="pending", item_copies=1):
    api = FakeClientAPI()
    api.customers["customer_a"]["payment_methods"][0]["brand"] = "visa"
    api.customers["customer_a"]["payment_methods"].append({"id": "card_other", "source": "credit_card", "brand": "visa", "last_four": "0002"})
    api.orders["#TEST1"].update(status=status, shipping_address=address(), fulfillments=[], payments=specification("cancel")["amount"]["rows"])
    api.orders["#TEST1"]["items"][0].update(name="Example mug", options={"color": "blue"})
    api.orders["#TEST1"]["items"] *= item_copies
    api.products["product_mug"]["items"].extend([
        {"item_id": "item_red", "options": {"color": "red"}, "price": 11.375, "available": True},
        {"item_id": "item_green", "options": {"color": "green"}, "price": 11.375, "available": True}])
    decision, state = advance(TurnInput(kind="user", content="customer_a a@example.test"), initial_state())
    call = decision.calls[0]
    customer = verify_customer(api, **call.arguments)
    _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, json.dumps(customer)),)), state)
    if with_order:
        decision, state = advance(TurnInput(kind="user", content="Read order #TEST1"), state)
        call = decision.calls[0]
        order = get_order(api, **call.arguments)
        _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, json.dumps(order)),)), state)
    if with_catalog:
        state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "catalog-fixture")
    return state, api


def agree(state, text="yes"):
    return advance(TurnInput(kind="user", content=text), state)


class ProposalPresentationTests(unittest.TestCase):
    def test_address_recap_has_every_field_target_and_single_confirmation_question(self):
        state, api = verified_state()
        before = deepcopy(state)
        calls = deepcopy(api.calls)
        decision, proposed = present_proposal(state, specification())
        self.assertFalse(decision.calls)
        self.assertEqual(decision.text, render_proposal(normalize_spec(specification())))
        for value in ("customer_a", "#TEST1", "2 Test St", "Testville", "CA", "US", "90002"):
            self.assertIn(value, decision.text)
        self.assertIn("Address line 2: null", decision.text)
        self.assertEqual(decision.text.count("?"), 1)
        self.assertEqual(state, before)
        self.assertEqual(api.calls, calls)
        proposed["proposals"][0]["spec"]["parameters"]["city"] = "mutated"
        self.assertEqual(state, before)

    def test_default_address_and_order_address_have_separate_targets_and_versions(self):
        state, _ = verified_state()
        _, state = present_proposal(state, specification("default_shipping_address"))
        _, state = agree(state)
        self.assertTrue(confirmation_matches(state, 1, specification("default_shipping_address")))
        _, updated = present_proposal(state, specification())
        self.assertEqual(updated["proposals"][-1]["version"], 2)
        self.assertEqual(updated["proposals"][0]["status"], "superseded")
        self.assertFalse(confirmation_matches(updated, 1, specification("default_shipping_address")))

    def test_payment_quote_and_destination_are_in_the_recap_and_snapshot(self):
        state, _ = verified_state()
        decision, state = present_proposal(state, specification("payment_method"))
        self.assertIn("Full order charge: 14.5", decision.text)
        self.assertIn("Payment method: card_other", decision.text)
        self.assertEqual(state["proposals"][-1]["spec"], specification("payment_method"))

    def test_cancellation_binds_each_original_charge_and_reason_without_aggregation(self):
        state, _ = verified_state()
        decision, state = present_proposal(state, specification("cancel"))
        self.assertIn("Reason: ordered by mistake", decision.text)
        self.assertIn("12.5 to card_a", decision.text)
        self.assertIn("2 to card_a", decision.text)
        self.assertIn("No aggregate refund amount", decision.text)
        self.assertEqual(len(state["proposals"][-1]["spec"]["amount"]["rows"]), 2)
        bad = specification("cancel")
        bad["amount"]["rows"][0]["amount"] = 999
        with self.assertRaises(InvalidProposal):
            present_proposal(state, bad)

    def test_complete_item_list_retains_duplicate_occurrences_and_explicit_closure(self):
        state, _ = verified_state(item_copies=2)
        spec = specification("modify_items")
        spec["parameters"]["replacements"] *= 2
        decision, state = present_proposal(state, spec)
        self.assertEqual(decision.text.count("Replace item_blue with item_red"), 2)
        self.assertIn("entire list is complete, with no other modifications", decision.text)
        self.assertIn("Signed price difference: -1.125", decision.text)
        _, confirmed = agree(state)
        self.assertTrue(confirmation_matches(confirmed, 1, spec))

    def test_unresolved_original_count_or_unsaved_method_cannot_be_presented(self):
        state, _ = verified_state()
        spec = specification("modify_items")
        spec["parameters"]["replacements"] *= 2
        with self.assertRaises(InvalidProposal):
            present_proposal(state, spec)
        spec = specification("modify_items")
        spec["parameters"]["replacements"][0]["existing_item_id"] = "missing"
        with self.assertRaises(InvalidProposal):
            present_proposal(state, spec)
        spec = specification("modify_items")
        spec["parameters"]["payment_method_id"] = "unsaved"
        with self.assertRaises(InvalidProposal):
            present_proposal(state, spec)

    def test_exchange_can_be_presented_only_for_delivered_state(self):
        state, _ = verified_state(status="delivered")
        _, state = present_proposal(state, specification("exchange"))
        _, confirmed = agree(state, "go ahead")
        self.assertTrue(confirmation_matches(confirmed, 1, specification("exchange")))
        pending, _ = verified_state()
        with self.assertRaises(InvalidProposal):
            present_proposal(pending, specification("exchange"))

    def test_unverified_or_legacy_verified_without_evidence_cannot_present(self):
        for state in (initial_state(), {**initial_state(), "customer_id": "customer_a", "identity": {"verified": True, "customer_id": "customer_a"}}):
            with self.assertRaises(InvalidProposal):
                present_proposal(state, specification("default_shipping_address"))

    def test_owned_reference_is_insufficient_without_an_accepted_order_read(self):
        state, _ = verified_state(with_order=False)
        with self.assertRaises(InvalidProposal):
            present_proposal(state, specification())
        decision, state = present_proposal(state, specification("default_shipping_address"))
        self.assertFalse(decision.calls)

    def test_cross_customer_order_and_locked_state_are_rejected(self):
        state, _ = verified_state()
        for field, value in (("customer_id", "customer_b"), ("order_id", "#TEST2")):
            spec = specification()
            spec["target"][field] = value
            with self.assertRaises(InvalidProposal):
                present_proposal(state, spec)
        for status in ("pending (items modified)", "processed", "cancelled", "return requested", "exchange requested"):
            locked, _ = verified_state(status=status)
            with self.subTest(status=status), self.assertRaises(InvalidProposal):
                present_proposal(locked, specification())

    def test_pending_read_and_handoff_do_not_allow_presentation(self):
        state, _ = verified_state()
        _, pending = advance(TurnInput(kind="user", content="Read order #TEST1"), state)
        with self.assertRaises(InvalidProposal):
            present_proposal(pending, specification())
        state["handoff"]["status"] = "accepted"
        with self.assertRaises(InvalidProposal):
            present_proposal(state, specification())

    def test_incomplete_address_extra_fields_and_model_confirmed_flag_are_rejected(self):
        state, _ = verified_state()
        for key in address():
            if key == "address_line_2":
                continue
            spec = specification()
            del spec["parameters"][key]
            with self.subTest(key=key), self.assertRaises(InvalidProposal):
                present_proposal(state, spec)
        for location, key in (("parameters", "name"), ("parameters", "confirmed"), (None, "confirmed"), ("target", "conversation_id")):
            spec = specification()
            (spec if location is None else spec[location])[key] = True
            with self.assertRaises(InvalidProposal):
                present_proposal(state, spec)

    def test_wrong_types_nonfinite_money_and_unpublished_selectors_are_rejected(self):
        for value in (None, True, "1.125", float("inf"), float("nan"), 10 ** 400):
            spec = specification("modify_items")
            spec["amount"]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_spec(spec)
        for key in ("quantity", "occurrence", "order_line_id"):
            spec = specification("modify_items")
            spec["parameters"]["replacements"][0][key] = 1
            with self.assertRaises(InvalidProposal):
                normalize_spec(spec)
        for value in (("card_a",), object(), {1: "bad"}):
            spec = specification("payment_method")
            spec["parameters"]["payment_method_id"] = value
            with self.assertRaises(InvalidProposal):
                normalize_spec(spec)

    def test_unknown_return_aggregate_cannot_be_promoted_by_a_numeric_quote(self):
        state, _ = verified_state(status="delivered")
        for amount in (None, 12.5, 0):
            spec = {"action": "return", "target": specification()["target"],
                    "parameters": {"item_ids": ["item_blue"], "refund_payment_method_id": "card_a"},
                    "amount": {"kind": "refund_estimate", "value": amount}}
            with self.assertRaises(InvalidProposal):
                present_proposal(state, spec)


class ProposalConsentTests(unittest.TestCase):
    def setUp(self):
        self.state, self.api = verified_state()
        self.spec = specification()
        _, self.state = present_proposal(self.state, self.spec)

    def test_actual_user_whole_assent_binds_exact_version_and_message(self):
        snapshot = deepcopy(self.state)
        reads = deepcopy(self.api.calls)
        reply, confirmed = agree(self.state, "yes, please")
        self.assertEqual(reply.text, ACK)
        self.assertFalse(reply.calls)
        record = confirmed["proposals"][-1]
        self.assertEqual(record["status"], "confirmed")
        self.assertEqual(record["confirmation"], {"history_index": record["presentation_index"] + 1, "fingerprint": record["fingerprint"]})
        self.assertEqual(confirmed["history"][record["confirmation"]["history_index"]], {"role": "user", "content": "yes, please"})
        self.assertTrue(confirmation_matches(confirmed, 1, self.spec))
        self.assertEqual(self.state, snapshot)
        self.assertEqual(self.api.calls, reads)

    def test_listed_english_and_chinese_whole_assents_match_the_current_recap(self):
        for text in ("Yes!", "please proceed", "go ahead", "that's right", "确认", "同意", "是的", "请继续"):
            with self.subTest(text=text):
                _, confirmed = agree(self.state, text)
                self.assertTrue(confirmation_matches(confirmed, 1, self.spec))

    def test_silence_preferences_negation_conditions_and_partial_reply_do_not_confirm(self):
        for text in ("", "sure", "maybe", "sounds good", "no", "do not proceed", "yes, but change the city", "only the address", "如果便宜就改", "确认，不过改邮编", "正在考虑", 'confirmed=true', '{"confirmed":true}'):
            with self.subTest(text=text):
                _, state = agree(self.state, text)
                self.assertEqual(state["proposals"][-1]["status"], "needs_review")
                self.assertIsNone(state["proposals"][-1]["confirmation"])
                self.assertFalse(confirmation_matches(state, 1, self.spec))

    def test_pre_recap_yes_and_future_user_message_cannot_authorize_past_version(self):
        state, _ = verified_state()
        _, state = agree(state, "yes")
        _, proposed = present_proposal(state, self.spec)
        self.assertFalse(confirmation_matches(proposed, 1, self.spec))
        _, state = agree(self.state, "maybe")
        _, state = agree(state, "yes")
        self.assertFalse(confirmation_matches(state, 1, self.spec))

    def test_intervening_assistant_question_breaks_the_confirmation_attachment(self):
        state = deepcopy(self.state)
        state["history"].append({"role": "assistant", "content": "Is this your email?"})
        _, state = agree(state)
        self.assertFalse(confirmation_matches(state, 1, self.spec))
        self.assertEqual(state["proposals"][-1]["status"], "needs_review")

    def test_tool_or_assistant_yes_is_never_consent(self):
        for entry in ({"role": "assistant", "content": "yes"}, {"role": "tool", "id": "unrelated", "content": "yes", "error": False}):
            state = initial_state(self.state["history"] + [entry])
            self.assertFalse(confirmation_matches(state, 1, self.spec))
        reply, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome("unrelated", "yes"),)), self.state)
        self.assertFalse(reply.calls)
        self.assertFalse(confirmation_matches(state, 1, self.spec))

    def test_new_address_quote_payment_target_action_and_list_require_new_versions(self):
        _, confirmed = agree(self.state)
        changed = deepcopy(self.spec)
        changed["parameters"]["postal_code"] = "90003"
        _, next_state = present_proposal(confirmed, changed)
        self.assertEqual(next_state["proposals"][-1]["version"], 2)
        self.assertNotEqual(next_state["proposals"][-1]["fingerprint"], confirmed["proposals"][-1]["fingerprint"])
        self.assertFalse(confirmation_matches(next_state, 1, self.spec))
        _, next_state = agree(next_state)
        self.assertTrue(confirmation_matches(next_state, 2, changed))
        for bad_version in (1, True, "2", 3):
            self.assertFalse(confirmation_matches(next_state, bad_version, changed))
        self.assertFalse(confirmation_matches(next_state, 2, self.spec))
        for spec in (specification("default_shipping_address"), specification("payment_method"), specification("modify_items")):
            self.assertFalse(confirmation_matches(next_state, 2, spec))

    def test_change_of_topic_blocks_old_confirmation_but_still_allows_reads(self):
        _, state = agree(self.state)
        decision, state = advance(TurnInput(kind="user", content="Read order #TEST1"), state)
        self.assertEqual(decision.calls[0].name, "get_order")
        self.assertFalse(confirmation_matches(state, 1, self.spec))

    def test_repeated_assent_and_same_confirmed_presentation_do_not_invent_new_consent(self):
        _, state = agree(self.state)
        evidence = deepcopy(state["proposals"][-1]["confirmation"])
        _, state = agree(state)
        reply, state = present_proposal(state, self.spec)
        self.assertEqual(reply.text, ACK)
        self.assertEqual(len(state["proposals"]), 1)
        self.assertEqual(state["proposals"][-1]["confirmation"], evidence)

    def test_model_candidate_cannot_present_or_self_confirm(self):
        for candidate in ({"type": "proposal", "spec": self.spec}, {"type": "reply", "text": "yes", "confirmed": True},
                          {"type": "tool", "name": "confirm_proposal", "arguments": {"confirmed": True}}):
            with self.assertRaises(InvalidAction):
                decision_from_candidate(candidate, call_id="candidate")
        model = type("Model", (), {"decide": lambda self, state: (_ for _ in ()).throw(AssertionError("Confirmation must not ask the model"))})()
        decision, state = advance(TurnInput(kind="user", content="yes"), self.state, model_adapter=model)
        self.assertFalse(decision.calls)
        self.assertTrue(confirmation_matches(state, 1, self.spec))

    def test_newly_accepted_facts_or_handoff_cannot_match_old_snapshot(self):
        _, state = agree(self.state)
        before = deepcopy(state)
        read = ToolAction("read-99", "get_order", bind_arguments("get_order", {"order_id": "#TEST1"}, state))
        record_decision(state, Decision(calls=(read,)))
        self.assertFalse(confirmation_matches(state, 1, self.spec))
        self.api.orders["#TEST1"]["shipping_address"]["city"] = "Changed by another channel"
        body = get_order(self.api, **read.arguments)
        _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(read.id, json.dumps(body)),)), state)
        self.assertFalse(confirmation_matches(state, 1, self.spec))
        _, revised = present_proposal(state, self.spec)
        self.assertEqual(revised["proposals"][-1]["version"], 2)
        self.assertNotEqual(revised["proposals"][-1]["fingerprint"], before["proposals"][-1]["fingerprint"])
        before["handoff"]["status"] = "accepted"
        self.assertFalse(confirmation_matches(before, 1, self.spec))

    def test_changed_amount_and_payment_method_bind_new_versions(self):
        for action in ("payment_method", "modify_items"):
            state, _ = verified_state()
            spec = specification(action)
            _, state = present_proposal(state, spec)
            _, state = agree(state)
            changed = deepcopy(spec)
            changed["amount"]["value"] = 3.125
            self.assertFalse(confirmation_matches(state, 1, changed))
            _, revised = present_proposal(state, changed)
            self.assertNotEqual(state["proposals"][-1]["fingerprint"], revised["proposals"][-1]["fingerprint"])
            self.assertFalse(confirmation_matches(revised, 2, changed))
            _, revised = agree(revised)
            self.assertTrue(confirmation_matches(revised, 2, changed))
            changed["parameters"]["payment_method_id"] = "card_a"
            self.assertFalse(confirmation_matches(revised, 2, changed))
            _, next_revision = present_proposal(revised, changed)
            self.assertEqual(next_revision["proposals"][-1]["version"], 3)
            self.assertFalse(confirmation_matches(next_revision, 2, spec))

    def test_ordered_replacement_list_is_not_sorted_or_deduplicated_for_consent(self):
        state, _ = verified_state(item_copies=2)
        spec = specification("modify_items")
        spec["parameters"]["replacements"].append({"existing_item_id": "item_blue", "replacement_item_id": "item_green"})
        _, state = present_proposal(state, spec)
        _, state = agree(state)
        changed = deepcopy(spec)
        changed["parameters"]["replacements"].reverse()
        self.assertFalse(confirmation_matches(state, 1, changed))
        _, revised = present_proposal(state, changed)
        self.assertEqual(revised["proposals"][-1]["spec"]["parameters"]["replacements"], changed["parameters"]["replacements"])
        self.assertNotEqual(revised["proposals"][-1]["fingerprint"], state["proposals"][-1]["fingerprint"])


class ProposalReviewRegressionTests(unittest.TestCase):
    def test_catalog_price_change_in_accepted_product_and_item_reads_invalidates_consent(self):
        for name, selectors in (("get_product", {"product_id": "product_mug"}), ("get_item", {"item_id": "item_red"})):
            state, api = verified_state()
            spec = specification("modify_items")
            _, state = present_proposal(state, spec)
            _, state = agree(state)
            api.products["product_mug"]["items"][1]["price"] = 20
            state = accept_read(state, api, name, selectors, "new-price")
            with self.subTest(name=name):
                self.assertEqual(check_confirmation(state, 1, spec)["code"], "facts_changed")
                self.assertFalse(confirmation_matches(state, 1, spec))
                _, revised = present_proposal(state, spec)
                self.assertEqual(revised["proposals"][-1]["version"], 2)
                self.assertEqual(initial_state(revised["history"])["proposals"], revised["proposals"])

    def test_target_availability_options_and_product_removal_block_old_consent(self):
        for change in ("availability", "options", "removal"):
            state, api = verified_state()
            spec = specification("modify_items")
            _, state = present_proposal(state, spec)
            _, state = agree(state)
            items = api.products["product_mug"]["items"]
            if change == "availability":
                items[1]["available"] = False
            elif change == "options":
                items[1]["options"]["color"] = "black"
            else:
                del items[1]
            state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "changed-target")
            with self.subTest(change=change):
                self.assertFalse(confirmation_matches(state, 1, spec))
                self.assertEqual(check_confirmation(state, 1, spec)["code"], "facts_changed" if change == "options" else "facts_unavailable")

    def test_missing_catalog_evidence_cannot_be_supplied_by_proposal_parameters(self):
        state, _ = verified_state(with_catalog=False)
        spec = specification("modify_items")
        with self.assertRaises(InvalidProposal):
            present_proposal(state, spec)
        spec["parameters"]["catalog"] = {"item_id": "item_red", "price": 11.375}
        with self.assertRaises(InvalidProposal):
            present_proposal(state, spec)

    def test_equal_catalog_reread_and_unrelated_variant_changes_preserve_consent(self):
        state, api = verified_state()
        spec = specification("modify_items")
        _, state = present_proposal(state, spec)
        _, state = agree(state)
        evidence = deepcopy(state["proposals"][-1]["confirmation"])
        api.products["product_mug"]["items"][2]["price"] = 99
        state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "same-target")
        self.assertTrue(confirmation_matches(state, 1, spec))
        state = accept_read(state, api, "get_item", {"item_id": "item_red"}, "same-item")
        self.assertTrue(confirmation_matches(state, 1, spec))
        _, same = present_proposal(state, spec)
        self.assertEqual(len(same["proposals"]), 1)
        self.assertEqual(same["proposals"][-1]["confirmation"], evidence)

    def test_catalog_provenance_and_future_or_rejected_reads_cannot_create_dependencies(self):
        state, _ = verified_state()
        spec = specification("modify_items")
        _, state = present_proposal(state, spec)
        event_index = state["proposals"][-1]["presentation_index"]
        tampered = deepcopy(state)
        tampered["history"][event_index]["proposal"]["facts"]["catalog"][0]["source"]["call_id"] = "invented"
        with self.assertRaises(InvalidState):
            clone_state(tampered)
        event = deepcopy(state["history"][event_index])
        before_catalog = next(i for i, e in enumerate(state["history"]) if any(c["id"] == "catalog-fixture" for c in e.get("tool_calls", [])))
        with self.assertRaises(InvalidProposal):
            initial_state(state["history"][:before_catalog] + [event] + state["history"][before_catalog:event_index])
        rejected = deepcopy(state["history"][:event_index])
        result_index = next(i for i, e in enumerate(rejected) if e.get("id") == "catalog-fixture")
        rejected[result_index]["error"] = True
        restored = initial_state(rejected)
        with self.assertRaises(InvalidProposal):
            present_proposal(restored, spec)

    def test_rejected_catalog_batch_does_not_poison_a_later_accepted_read(self):
        state, api = verified_state(with_catalog=False)
        call = ToolAction("bad-catalog", "get_product", bind_arguments("get_product", {"product_id": "product_mug"}, state))
        record_decision(state, Decision(calls=(call,)))
        _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, '{"product_id":"wrong"}'),)), state)
        state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "good-catalog")
        _, proposed = present_proposal(state, specification("modify_items"))
        self.assertEqual(proposed["proposals"][-1]["facts"]["catalog"][0]["source"]["call_id"], "good-catalog")

    def test_equal_int_float_amounts_preserve_version_evidence_and_original_precision(self):
        for value in (1, -1, 0, 2 ** 53):
            state, _ = verified_state()
            spec = specification("modify_items")
            spec["amount"]["value"] = value
            _, state = present_proposal(state, spec)
            _, state = agree(state)
            changed = deepcopy(spec)
            changed["amount"]["value"] = float(value)
            evidence = deepcopy(state["proposals"][-1]["confirmation"])
            with self.subTest(value=value):
                self.assertTrue(confirmation_matches(state, 1, changed))
                _, repeated = present_proposal(state, changed)
                self.assertEqual(len(repeated["proposals"]), 1)
                self.assertIs(type(repeated["proposals"][-1]["spec"]["amount"]["value"]), int)
                self.assertEqual(repeated["proposals"][-1]["confirmation"], evidence)
        changed["amount"]["value"] = value + 1
        self.assertFalse(confirmation_matches(state, 1, changed))
        changed["amount"]["value"] = True
        self.assertFalse(confirmation_matches(state, 1, changed))

    def test_structured_confirmation_codes_and_boolean_failure_are_consistent(self):
        state, _ = verified_state()
        spec = specification()
        self.assertEqual(check_confirmation(state, 1, spec)["code"], "proposal_required")
        _, state = present_proposal(state, spec)
        self.assertEqual(check_confirmation(state, 1, spec)["code"], "confirmation_required")
        _, confirmed = agree(state)
        self.assertEqual(check_confirmation(confirmed, 1, spec)["code"], "consent_matches")
        self.assertTrue(check_confirmation(confirmed, 1, spec)["details"]["confirmation_matches"])
        invalid = deepcopy(confirmed)
        invalid["proposals"][0]["status"] = "fake"
        for broken, version, candidate, code in ((invalid, 1, spec, "invalid_state"), (None, 1, spec, "invalid_state"),
                (confirmed, True, spec, "invalid_version"), (confirmed, 1, {}, "invalid_specification"),
                (confirmed, 2, spec, "version_mismatch"), (confirmed, 1, specification("default_shipping_address"), "specification_mismatch")):
            with self.subTest(code=code):
                self.assertEqual(check_confirmation(broken, version, candidate)["code"], code)
                self.assertFalse(confirmation_matches(broken, version, candidate))
        read = ToolAction("pending-check", "get_order", bind_arguments("get_order", {"order_id": "#TEST1"}, confirmed))
        record_decision(confirmed, Decision(calls=(read,)))
        self.assertEqual(check_confirmation(confirmed, 1, spec)["code"], "pending_reads")
        confirmed["handoff"]["status"] = "accepted"
        self.assertEqual(check_confirmation(confirmed, 1, spec)["code"], "handoff_blocks_consent")

    def test_structured_ack_retains_evidence_independently_of_wording(self):
        state, _ = verified_state()
        _, state = present_proposal(state, specification())
        _, state = agree(state)
        evidence = deepcopy(state["proposals"][-1]["confirmation"])
        state["history"][-1]["content"] = "已记录同意，尚未执行变更。"
        _, state = agree(state)
        self.assertEqual(state["proposals"][-1]["confirmation"], evidence)
        self.assertTrue(confirmation_matches(state, 1, specification()))
        self.assertEqual(initial_state(state["history"])["proposals"], state["proposals"])
        state["history"][-1].pop("proposal_ack")
        _, state = agree(state)
        self.assertFalse(confirmation_matches(state, 1, specification()))

    def test_ack_metadata_never_creates_consent_and_rejects_wrong_version_or_reference(self):
        state, _ = verified_state()
        _, proposed = present_proposal(state, specification())
        _, confirmed = agree(proposed)
        ack = deepcopy(confirmed["history"][-1])
        with self.assertRaises(InvalidState):
            forged = deepcopy(proposed)
            forged["history"].append(ack)
            clone_state(forged)
        for key, value in (("version", True), ("version", 2), ("confirmation_index", 0), ("fingerprint", "fake")):
            forged = deepcopy(confirmed)
            forged["history"][-1]["proposal_ack"][key] = value
            with self.subTest(key=key), self.assertRaises(InvalidState):
                clone_state(forged)

    def test_schema1_missing_key_and_unknown_confirmation_metadata_remain_rejected(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/m3_schema1_state.json").read_text(encoding="utf-8"))["state"]
        missing = deepcopy(fixture)
        del missing["proposals"]
        with self.assertRaises(InvalidState):
            clone_state(missing)
        fixture["history"].append({"role": "assistant", "content": ACK, "proposal_ack": {"version": 1}})
        with self.assertRaises(InvalidState):
            clone_state(fixture)


class ProposalRecoveryTests(unittest.TestCase):
    def setUp(self):
        state, _ = verified_state()
        self.spec = specification()
        _, self.proposed = present_proposal(state, self.spec)
        _, self.confirmed = agree(self.proposed)

    def test_fixed_schema1_fixture_migrates_without_mutating_identity_history(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/m3_schema1_state.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["source_commit"], "9b323d3a2ed4d203990e0337185bc2caedf6701f")
        legacy = fixture["state"]
        self.assertEqual(legacy["schema_version"], 1)
        self.assertEqual(legacy["proposals"], [])
        snapshot = deepcopy(legacy)
        migrated = clone_state(legacy)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertEqual(migrated["history"], legacy["history"])
        self.assertEqual(migrated["identity_evidence"], legacy["identity_evidence"])
        self.assertEqual(legacy, snapshot)
        legacy["proposals"] = [{"confirmed": True}]
        with self.assertRaises(InvalidState):
            clone_state(legacy)

    def test_json_clone_and_history_restore_rebuild_identical_consent_without_api(self):
        snapshot = deepcopy(self.confirmed)
        with patch.object(FakeClientAPI, "request", side_effect=AssertionError("Recovery must not call API")):
            cloned = clone_state(json.loads(json.dumps(self.confirmed)))
            restored = initial_state(self.confirmed["history"])
        self.assertEqual(restored["proposals"], cloned["proposals"])
        self.assertTrue(confirmation_matches(restored, 1, self.spec))
        self.assertEqual(self.confirmed, snapshot)

    def test_plain_platform_recaps_have_no_metadata_and_do_not_restore_consent(self):
        plain = [{k: v for k, v in e.items() if k not in {"proposal", "proposal_ack"}} for e in self.confirmed["history"]]
        restored = initial_state(plain)
        self.assertEqual(restored["proposals"], [])
        self.assertFalse(confirmation_matches(restored, 1, self.spec))

    def test_ledger_flags_versions_and_confirmation_indices_must_match_history(self):
        for field, value in (("status", "proposed"), ("version", 2), ("version", True), ("confirmation", {"history_index": 0, "fingerprint": "fake"}),
                             ("presentation_index", 0), ("fingerprint", "fake")):
            state = deepcopy(self.confirmed)
            state["proposals"][0][field] = value
            with self.subTest(field=field), self.assertRaises(InvalidState):
                clone_state(state)
        state = deepcopy(self.proposed)
        state["proposals"][0]["status"] = "confirmed"
        with self.assertRaises(InvalidState):
            clone_state(state)

    def test_deleted_or_retyped_user_evidence_and_modified_recap_are_rejected(self):
        index = self.confirmed["proposals"][0]["confirmation"]["history_index"]
        for role in ("assistant", "tool"):
            state = deepcopy(self.confirmed)
            state["history"][index]["role"] = role
            with self.assertRaises(InvalidState):
                clone_state(state)
        state = deepcopy(self.confirmed)
        del state["history"][index]
        with self.assertRaises(InvalidState):
            clone_state(state)
        state = deepcopy(self.confirmed)
        state["history"][state["proposals"][0]["presentation_index"]]["content"] = "Summary: customer agreed"
        with self.assertRaises(InvalidState):
            clone_state(state)

    def test_metadata_facts_request_order_and_mixed_tool_presentation_are_checked(self):
        index = self.proposed["proposals"][0]["presentation_index"]
        for field, value in (("request_index", index + 1), ("version", True), ("facts", {}), ("fingerprint", "fake")):
            state = deepcopy(self.proposed)
            state["history"][index]["proposal"][field] = value
            with self.subTest(field=field), self.assertRaises(InvalidState):
                clone_state(state)
        state = deepcopy(self.proposed)
        state["history"][index]["tool_calls"] = [{"id": "write", "name": "cancel_order", "arguments": {}}]
        with self.assertRaises(InvalidState):
            clone_state(state)

    def test_future_identity_proof_cannot_authorize_a_past_proposal(self):
        index = self.proposed["proposals"][0]["presentation_index"]
        event = deepcopy(self.proposed["history"][index])
        # The actual verification arrives after the forged early presentation.
        history = [{"role": "user", "content": "Change my address"}, event] + self.proposed["history"][:index]
        event["proposal"]["request_index"] = 0
        with self.assertRaises(ValueError):
            initial_state(history)

    def test_model_projection_and_application_adapter_use_real_sdk_offline(self):
        root = Path(__file__).resolve().parents[1]
        interpreter = root / ".venv/Scripts/python.exe"
        self.assertTrue(interpreter.is_file(), "M3.2 requires the project SDK interpreter; do not skip")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(PYTHON_DOTENV_DISABLED="1", HF_HUB_OFFLINE="1", LITELLM_TELEMETRY="False", LITELLM_LOCAL_MODEL_COST_MAP="True")
        result = subprocess.run([str(interpreter), str(root / "tests/sdk_m3_checks.py")], cwd=root, env=env,
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("M3_NETWORK_GUARD_CHECK_PASSED; 2 controlled audit probes; actual-path network attempts 0", result.stdout)
        self.assertIn("M3_SDK_CHECK_PASSED; network attempts 0; gateway fake", result.stdout)


if __name__ == "__main__":
    unittest.main()
