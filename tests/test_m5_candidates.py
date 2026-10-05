"""M5.1 distinguishing selection and canonical evidence tests; no live API."""
import json
import sys
import unittest
from copy import deepcopy
from decimal import localcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.domain.candidate_selection import select_candidates
from support_agent.candidate_session import assess_candidates
from support_agent.protocol import Decision, ToolAction, ToolOutcome, TurnInput
from support_agent.read_session import bind_arguments, record_decision
from support_agent.state import clone_state, initial_state
from support_agent.turns import advance
from test_m3_proposals import accept_read, verified_state


def original():
    return [{"item_id": "old", "product_id": "bottle", "name": "Bottle", "price": 15,
             "options": {"color": "blue", "capacity": "500 ml", "waterproof": "yes"}}]


def item(item_id, *, color="red", capacity="500 ml", waterproof="yes", price=10, available=True):
    return {"item_id": item_id, "options": {"color": color, "capacity": capacity, "waterproof": waterproof},
            "price": price, "available": available}


def products(*items):
    return [{"product_id": "bottle", "name": "Bottle", "items": list(items)}]


def criteria(**changes):
    value = {"hard": [], "change": ["color"], "relax": [], "preferences": [], "fallbacks": [], "ranking": []}
    value.update(changes)
    return value


def predicate(field, op, value, **kw):
    return dict(field=field, op=op, value=value, **kw)


class CandidateSelectionTests(unittest.TestCase):
    def choose(self, items, request=None, source=None):
        return select_candidates(source or original(), "old", products(*items), criteria() if request is None else request)

    def selected(self, result, expected, branch=0):
        self.assertEqual(result["code"], "candidate_selected")
        self.assertEqual(result["details"]["selected"]["item_id"], expected)
        self.assertEqual(result["details"]["branch"], branch)
        self.assertIs(result["details"]["write_authorized"], False)

    def test_hard_stock_retention_precede_preference_and_price(self):
        request = criteria(hard=[predicate("capacity", "gte", "500 ml")],
                           preferences=[{"field": "color", "tiers": [["green"], ["red"]]}],
                           ranking=[{"field": "price", "direction": "min"}])
        result = self.choose([item("small", color="green", capacity="250 ml", price=1),
                             item("sold", color="green", available=False, price=1),
                             item("wrong", color="green", waterproof="no", price=1), item("good", price=20)], request)
        self.selected(result, "good")
        self.assertEqual(result["details"]["trace"][0], {"branch": 0, "hard_matches": 3, "in_stock": 2,
                                                       "preserved_matches": 1, "unresolved_comparisons": 0})

    def test_missing_decision_basis_and_equal_rank_require_customer_choice(self):
        for request in (criteria(), criteria(ranking=[{"field": "price", "direction": "min"}])):
            with self.subTest(request=request):
                result = self.choose([item("z"), item("a")], request)
                self.assertEqual(result["code"], "candidate_choice_required")
                self.assertIsNone(result["details"]["selected"])
                self.assertEqual([i["item_id"] for i in result["details"]["finalists"]], ["z", "a"])

    def test_catalog_reordering_does_not_break_a_tie_or_change_unique_choice(self):
        request = criteria(ranking=[{"field": "price", "direction": "min"}])
        for items in ([item("expensive", price=30), item("cheap", price=2)], [item("cheap", price=2), item("expensive", price=30)]):
            self.selected(self.choose(items, request), "cheap")
        self.assertEqual(self.choose([item("b"), item("a")])["code"], "candidate_choice_required")

    def test_preference_absence_keeps_candidates_and_does_not_trigger_fallback(self):
        request = criteria(preferences=[{"field": "color", "tiers": [["silver"]]}],
                           fallbacks=[{"hard": [predicate("color", "eq", "green")], "change": ["color"], "relax": []}])
        self.selected(self.choose([item("red")], request), "red")

    def test_preference_tiers_apply_in_customer_order(self):
        for tiers, expected in (([["green"], ["red"]], "green"), ([["red"], ["green"]], "red")):
            request = criteria(preferences=[{"field": "color", "tiers": tiers}])
            self.selected(self.choose([item("red"), item("green", color="green")], request), expected)

    def test_unordered_colors_within_a_tier_remain_tied(self):
        request = criteria(preferences=[{"field": "color", "tiers": [["red", "green"]]}])
        self.assertEqual(self.choose([item("red"), item("green", color="green")], request)["code"], "candidate_choice_required")

    def test_soft_preference_cannot_relax_an_unmentioned_original_attribute(self):
        request = criteria(preferences=[{"field": "waterproof", "tiers": [["no"]]}])
        self.selected(self.choose([item("preferred", waterproof="no"), item("retained")], request), "retained")

    def test_explicit_relaxation_changes_only_that_attribute(self):
        request = criteria(relax=["waterproof"])
        self.selected(self.choose([item("relaxed", waterproof="no"), item("wrong_size", capacity="1 l")], request), "relaxed")

    def test_unlimited_budget_does_not_relax_other_attributes(self):
        self.selected(self.choose([item("size_changed", capacity="1 l", price=1), item("right", price=100000)]), "right")

    def test_no_candidates_requires_clarification_without_invented_relaxation(self):
        result = self.choose([item("wrong", waterproof="no")])
        self.assertEqual(result["code"], "no_eligible_candidates")
        self.assertEqual(result["details"]["eligible_candidates"], [])

    def test_fallback_is_used_only_after_zero_eligible_primary_matches(self):
        request = criteria(hard=[predicate("color", "eq", "silver")], fallbacks=[
            {"hard": [predicate("color", "eq", "green")], "change": ["color"], "relax": []},
            {"hard": [predicate("color", "eq", "red")], "change": ["color"], "relax": []}])
        self.selected(self.choose([item("red"), item("green", color="green")], request), "green", 1)
        self.selected(self.choose([item("silver", color="silver", price=100), item("green", color="green")], request), "silver")

    def test_unavailable_primary_can_activate_explicit_fallback(self):
        request = criteria(hard=[predicate("color", "eq", "silver")], fallbacks=[
            {"hard": [predicate("color", "eq", "red")], "change": ["color"], "relax": []}])
        self.selected(self.choose([item("silver", color="silver", available=False), item("red")], request), "red", 1)

    def test_primary_tie_never_activates_fallback(self):
        request = criteria(fallbacks=[{"hard": [predicate("color", "eq", "green")], "change": ["color"], "relax": []}])
        result = self.choose([item("red1"), item("red2"), item("green", color="green")], request)
        self.assertEqual(result["code"], "candidate_choice_required")
        self.assertEqual(len(result["details"]["trace"]), 1)

    def test_fallback_retains_unmentioned_original_attributes(self):
        request = criteria(hard=[predicate("color", "eq", "silver")], fallbacks=[
            {"hard": [predicate("color", "eq", "red")], "change": ["color"], "relax": []}])
        self.assertEqual(self.choose([item("wrong", waterproof="no")], request)["code"], "no_eligible_candidates")

    def test_fallback_applies_its_own_change_and_relax_and_retains_other_attributes(self):
        request = criteria(hard=[predicate("color", "eq", "silver")], fallbacks=[
            {"hard": [predicate("capacity", "gt", {"original": "capacity"})],
             "change": ["capacity"], "relax": ["waterproof"]}])
        result = self.choose([item("larger_relaxed", color="blue", capacity="1 l", waterproof="no"),
                              item("wrong_unmentioned_color", color="red", capacity="2 l", waterproof="no")], request)
        self.selected(result, "larger_relaxed", 1)
        self.assertEqual([i["item_id"] for i in result["details"]["eligible_candidates"]], ["larger_relaxed"])

    def test_unknown_numeric_semantics_prevent_false_no_match_and_fallback(self):
        request = criteria(change=["capacity", "color"], hard=[predicate("capacity", "gt", "500 ml")], fallbacks=[
            {"hard": [], "change": ["color"], "relax": []}])
        result = self.choose([item("unparsed", capacity="large"), item("fallback")], request)
        self.assertEqual(result["code"], "comparison_unavailable")
        self.assertEqual(len(result["details"]["trace"]), 1)

    def test_numeric_comparison_uses_values_and_compatible_units(self):
        request = criteria(change=["capacity", "color"], hard=[predicate("capacity", "gte", "750 ml")],
                           ranking=[{"field": "capacity", "direction": "max"}])
        self.selected(self.choose([item("900", capacity="900 ml"), item("one_liter", capacity="1 l")], request), "one_liter")

    def test_incompatible_units_do_not_sort_lexicographically(self):
        request = criteria(change=["capacity", "color"], ranking=[{"field": "capacity", "direction": "max"}])
        self.assertEqual(self.choose([item("volume", capacity="1 l"), item("length", capacity="900 cm")], request)["code"], "comparison_unavailable")

    def test_ranking_unknown_exposes_remaining_candidates_and_failed_priority_without_selection(self):
        request = criteria(change=["color", "capacity"],
                           preferences=[{"field": "color", "tiers": [["red"]]}],
                           ranking=[{"field": "price", "direction": "min"}, {"field": "capacity", "direction": "max"}])
        result = self.choose([item("one", capacity="1 l", price=10), item("unknown", capacity="large", price=10),
                              item("expensive", capacity="2 l", price=20), item("less_preferred", color="green", price=1)], request)
        self.assertEqual(result["code"], "comparison_unavailable")
        self.assertEqual([i["item_id"] for i in result["details"]["finalists"]], ["one", "unknown"])
        self.assertIsNone(result["details"]["selected"])
        self.assertEqual(result["details"]["comparison_field"], "capacity")
        self.assertEqual(result["details"]["comparison_reason"], "An option has no documented numeric interpretation")
        self.assertEqual([r["field"] for r in result["details"]["ranking_trace"]], ["price"])
        self.assertIs(result["details"]["write_authorized"], False)

    def test_explicit_ordinal_order_handles_cpu_tiers_without_string_sort(self):
        source = original(); source[0]["options"]["capacity"] = "i3"
        request = criteria(change=["capacity", "color"], hard=[predicate("capacity", "gte", "i7", order=["i3", "i5", "i7", "i9"])],
                           ranking=[{"field": "price", "direction": "min"}])
        self.selected(self.choose([item("i5", capacity="i5", price=1), item("i7", capacity="i7", price=20), item("i9", capacity="i9", price=30)], request, source), "i7")

    def test_ordinal_values_outside_user_order_require_information(self):
        request = criteria(change=["capacity", "color"], ranking=[{"field": "capacity", "direction": "max", "order": ["i5", "i7"]}])
        self.assertEqual(self.choose([item("one", capacity="i5"), item("unknown", capacity="i9")], request)["code"], "comparison_unavailable")

    def test_multiobjective_priority_max_resolution_then_cheapest_tie(self):
        request = criteria(change=["capacity", "color"], ranking=[{"field": "capacity", "direction": "max"}, {"field": "price", "direction": "min"}])
        self.selected(self.choose([item("low", capacity="10 mp", price=1), item("high_expensive", capacity="20 mp", price=30), item("high_cheap", capacity="20 mp", price=20)], request), "high_cheap")
        request["ranking"].reverse()
        self.selected(self.choose([item("low", capacity="10 mp", price=1), item("high", capacity="20 mp", price=20)], request), "low")

    def test_zero_budget_and_price_cap_are_hard_not_net_difference(self):
        request = criteria(hard=[predicate("price", "lte", 0)])
        self.selected(self.choose([item("free", price=0), item("paid", price=1)], request), "free")
        request["hard"][0]["value"] = original()[0]["price"]
        self.selected(self.choose([item("original_cap", price=15), item("over", price=15.001)], request), "original_cap")

    def test_each_candidate_keeps_its_own_price_and_complete_options(self):
        result = self.choose([item("red", price=99), item("green", color="green", price=1)], criteria(hard=[predicate("color", "eq", "red")]))
        self.selected(result, "red")
        self.assertEqual(result["details"]["selected"]["price"], 99)
        self.assertEqual(result["details"]["original"]["price"], 15)

    def test_same_product_and_different_variant_are_required(self):
        catalog = products(item("old", color="blue")); catalog += [{"product_id": "other", "name": "Bottle", "items": [item("wrong_product")]}]
        result = select_candidates(original(), "old", catalog, criteria())
        self.assertEqual(result["code"], "no_eligible_candidates")

    def test_catalog_item_does_not_require_product_id(self):
        self.selected(self.choose([item("red")]), "red")
        self.assertNotIn("product_id", self.choose([item("red")])["details"]["selected"])

    def test_empty_complete_catalog_differs_from_missing_product_envelope(self):
        self.assertEqual(self.choose([])["code"], "no_eligible_candidates")
        self.assertEqual(select_candidates(original(), "old", [], criteria())["code"], "product_catalog_required")

    def test_missing_or_extra_option_keys_cannot_fake_retention(self):
        for extra in (False, True):
            variant = item("wrong")
            if extra:
                variant["options"]["new_attribute"] = "yes"
            else:
                variant["options"].pop("waterproof")
            self.assertEqual(self.choose([variant])["code"], "no_eligible_candidates")

    def test_malformed_catalog_is_not_no_stock_or_a_fallback(self):
        for variant in (dict(item("bad"), available=1), dict(item("bad"), price=True), dict(item("bad"), price=float("nan"))):
            self.assertEqual(self.choose([variant])["code"], "catalog_facts_required")
        self.assertEqual(self.choose([item("repeat"), item("repeat")])["code"], "catalog_facts_required")

    def test_closed_criteria_reject_quantity_unknown_fields_and_nonfinite_numbers(self):
        bad = [criteria(quantity=2), criteria(change=["unknown"]), criteria(relax=["color"]), criteria(hard=[predicate("price", "lte", True)]),
               criteria(hard=[predicate("price", "lte", float("inf"))]), criteria(ranking=[{"field": "price", "direction": "best"}])]
        for request in bad:
            with self.subTest(request=request):
                result = self.choose([item("red")], request)
                self.assertEqual(result["code"], "invalid_selection_criteria")
                self.assertIs(result["details"]["input_error"], True)

    def test_duplicate_and_malformed_preference_or_rank_contracts_are_rejected(self):
        bad = [criteria(preferences=[{"field": "color", "tiers": [["red"], ["red"]]}]), criteria(preferences=[{"field": "color", "tiers": []}]),
               criteria(ranking=[{"field": "price", "direction": "min"}] * 2), criteria(fallbacks=[{}]), criteria(hard=[predicate("color", "in", [])])]
        for request in bad:
            self.assertEqual(self.choose([item("red")], request)["code"], "invalid_selection_criteria")

    def test_explicit_order_is_rejected_for_equality_and_membership(self):
        for op, value in (("eq", "red"), ("in", ["red", "green"])):
            with self.subTest(op=op):
                request = criteria(hard=[predicate("color", op, value, order=["red", "green"])])
                result = self.choose([item("red")], request)
                self.assertEqual(result["code"], "invalid_selection_criteria")
                self.assertIs(result["details"]["input_error"], True)

    def test_out_of_range_numeric_argument_and_text_measurement_have_distinct_error_channels(self):
        for value, expected in ((10 ** 309, "invalid_selection_criteria"), ("1e999999 l", "comparison_unavailable")):
            with self.subTest(expected=expected):
                request = criteria(change=["color", "capacity"], hard=[predicate("capacity", "gt", value)])
                result = self.choose([item("one", capacity="1 l")], request)
                self.assertEqual(result["code"], expected)
                self.assertEqual(result["details"].get("input_error", False), expected == "invalid_selection_criteria")
                self.assertIs(result["details"]["write_authorized"], False)

    def test_duplicate_original_occurrences_remain_distinguishable_when_needed(self):
        source = original() * 2
        self.selected(self.choose([item("red")], source=source), "red")
        source[1] = deepcopy(source[1]); source[1]["price"] = 16
        self.assertEqual(self.choose([item("red")], source=source)["code"], "instance_selection_unavailable")

    def test_pure_result_owns_facts_and_preserves_all_inputs(self):
        source, catalog, request = original(), products(item("red")), criteria()
        before = deepcopy((source, catalog, request))
        first = select_candidates(source, "old", catalog, request)
        self.assertEqual(first, select_candidates(source, "old", catalog, request))
        first["details"]["selected"]["options"]["color"] = "mutated"
        self.assertEqual((source, catalog, request), before)

    def test_bad_source_id_is_a_repairable_input_error(self):
        self.assertEqual(select_candidates(original(), {}, products(item("red")), criteria())["code"], "invalid_source_item")

    def test_known_hard_exclusion_beats_unrelated_unknown_measurements(self):
        request = criteria(change=["capacity", "color"], hard=[predicate("capacity", "gt", "500 ml"), predicate("color", "eq", "red")])
        self.selected(self.choose([item("excluded", color="green", capacity="large"), item("chosen", capacity="1 l")], request), "chosen")

    def test_excluded_unknowns_do_not_inflate_unresolved_comparison_trace(self):
        request = criteria(change=["color", "capacity"], hard=[predicate("capacity", "gt", "500 ml"), predicate("color", "eq", "red")])
        result = self.choose([item("sold", capacity="large", available=False), item("hard_excluded", color="green", capacity="large"),
                              item("retention_excluded", waterproof="no", capacity="large"), item("chosen", capacity="1 l")], request)
        self.selected(result, "chosen")
        self.assertEqual(result["details"]["trace"][0]["unresolved_comparisons"], 0)

    def test_every_decision_including_input_and_missing_facts_is_not_write_permission(self):
        for result in (self.choose([]), self.choose([item("red")]), self.choose([item("a"), item("b")]),
                       self.choose([item("bad")], criteria(quantity=2)), select_candidates(None, "old", [], criteria())):
            self.assertIs(result["details"]["write_authorized"], False)

    def test_original_price_and_size_references_use_order_not_current_source_catalog(self):
        request = criteria(change=["capacity", "color"], hard=[predicate("price", "lte", {"original": "price"}),
                                                               predicate("capacity", "gt", {"original": "capacity"})])
        self.selected(self.choose([item("old", color="blue", price=999), item("same_size"), item("bigger", capacity="1 l", price=15),
                                   item("over_cap", capacity="2 l", price=16)], request), "bigger")

    def test_invalid_original_reference_is_an_input_error(self):
        self.assertEqual(self.choose([item("red")], criteria(hard=[predicate("price", "lte", {"original": "missing"})]))["code"], "invalid_selection_criteria")

    def test_extreme_measurement_exponents_require_information_without_decimal_exceptions(self):
        request = criteria(change=["capacity", "color"], hard=[predicate("capacity", "gt", "500 ml")])
        for value in ("1e999999 l", "1e-999999 ml"):
            with self.subTest(value=value):
                self.assertEqual(self.choose([item("extreme", capacity=value)], request)["code"], "comparison_unavailable")

    def test_numeric_unit_conversion_does_not_depend_on_callers_decimal_context(self):
        request = criteria(change=["capacity", "color"], ranking=[{"field": "capacity", "direction": "max"}])
        with localcontext() as context:
            context.prec, context.Emax = 1, 1
            self.selected(self.choose([item("900", capacity="900 ml"), item("one_liter", capacity="1 l")], request), "one_liter")


def selection_state(*, with_catalog=True, with_order=True):
    state, api = verified_state(with_catalog=with_catalog, with_order=with_order)
    request = {"candidate_selection": {"order_id": "#TEST1", "item_id": "item_blue",
                                      "criteria": criteria(hard=[predicate("color", "eq", "red")])}}
    _, state = advance(TurnInput("user", json.dumps(request)), state)
    index = next(i for i in range(len(state["history"])-1, -1, -1) if state["history"][i]["role"] == "user")
    return state, api, index


class CandidateEvidenceTests(unittest.TestCase):
    def test_actual_user_request_and_accepted_order_catalog_select_without_changing_ledger(self):
        state, _, index = selection_state()
        before = deepcopy(state)
        result, copied = assess_candidates(state, index)
        self.assertEqual(result["code"], "candidate_selected")
        self.assertEqual(result["details"]["selected"]["item_id"], "item_red")
        self.assertEqual(copied, before)
        self.assertEqual(state, before)
        self.assertEqual(copied["proposals"], [])

    def test_application_entry_and_history_restore_agree(self):
        from support_agent.application import CustomerAgent
        state, _, index = selection_state()
        direct = assess_candidates(state, index)[0]
        self.assertEqual(CustomerAgent().assess_candidates(state, index)[0], direct)
        self.assertEqual(assess_candidates(initial_state(state["history"]), index)[0], direct)

    def test_missing_complete_product_or_order_requires_read_not_fallback(self):
        for flags, code in (({"with_catalog": False}, "product_read_required"), ({"with_order": False}, "order_read_required")):
            state, _, index = selection_state(**flags)
            self.assertEqual(assess_candidates(state, index)[0]["code"], code)

    def test_unverified_session_cannot_use_caller_supplied_criteria_as_identity(self):
        state = initial_state([{"role": "user", "content": json.dumps({"candidate_selection": {"order_id": "#TEST1", "item_id": "item_blue", "criteria": criteria()}})}])
        self.assertEqual(assess_candidates(state, 0)[0]["code"], "identity_required")

    def test_assistant_text_and_future_or_stale_user_indices_are_not_request_sources(self):
        state, _, index = selection_state()
        original_request = state["history"][index]["content"]
        state["history"].append({"role": "assistant", "content": original_request})
        result, copied = assess_candidates(state, len(state["history"]) - 1)
        self.assertEqual(result["code"], "actual_selection_request_required")
        self.assertEqual(copied["history"][index]["content"], original_request)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "candidate_selected")
        for bad in (True, index-1, index+100, None):
            self.assertEqual(assess_candidates(state, bad)[0]["code"], "actual_selection_request_required")
        _, state = advance(TurnInput("user", "different request"), state)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "actual_selection_request_required")

    def test_wrong_owned_order_and_unknown_request_keys_are_rejected(self):
        for change, expected in (({"order_id": "#OTHER"}, "order_not_owned"), ({"confirmed": True}, "invalid_selection_request")):
            state, _, _ = selection_state()
            req = {"order_id": "#TEST1", "item_id": "item_blue", "criteria": criteria()}; req.update(change)
            _, state = advance(TurnInput("user", json.dumps({"candidate_selection": req})), state)
            index = next(i for i in range(len(state["history"])-1, -1, -1) if state["history"][i]["role"] == "user")
            self.assertEqual(assess_candidates(state, index)[0]["code"], expected)

    def test_latest_failed_product_read_blocks_old_complete_catalog(self):
        state, _, index = selection_state()
        call = ToolAction("failed-product", "get_product", bind_arguments("get_product", {"product_id": "product_mug"}, state))
        record_decision(state, Decision(calls=(call,)))
        _, state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "untrusted body", True),)), state)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "product_read_required")

    def test_latest_failed_order_read_blocks_old_order(self):
        state, _, index = selection_state()
        call = ToolAction("failed-order", "get_order", bind_arguments("get_order", {"order_id": "#TEST1"}, state))
        record_decision(state, Decision(calls=(call,)))
        _, state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "failed", True),)), state)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "order_read_required")

    def test_pending_read_blocks_assessment_until_complete_batch_acceptance(self):
        state, _, index = selection_state()
        call = ToolAction("pending-product", "get_product", bind_arguments("get_product", {"product_id": "product_mug"}, state))
        record_decision(state, Decision(calls=(call,)))
        self.assertEqual(assess_candidates(state, index)[0]["code"], "pending_workflow")

    def test_latest_accepted_variant_updates_stock_and_keeps_complete_membership(self):
        state, api, index = selection_state()
        next(i for i in api.products["product_mug"]["items"] if i["item_id"] == "item_red")["available"] = False
        state = accept_read(state, api, "get_item", {"item_id": "item_red"}, "updated-item")
        self.assertEqual(assess_candidates(state, index)[0]["code"], "no_eligible_candidates")

    def test_failed_variant_read_cannot_be_ignored_or_activate_a_fallback(self):
        state, _, index = selection_state()
        call = ToolAction("failed-item", "get_item", bind_arguments("get_item", {"item_id": "item_red"}, state))
        record_decision(state, Decision(calls=(call,)))
        _, state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "failed", True),)), state)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "product_read_required")

    def test_individual_item_read_cannot_prove_catalog_completeness(self):
        state, api, index = selection_state(with_catalog=False)
        state = accept_read(state, api, "get_item", {"item_id": "item_blue"}, "one-item")
        self.assertEqual(assess_candidates(state, index)[0]["code"], "product_read_required")

    def test_corrupted_state_is_quarantined_at_application_boundary(self):
        from support_agent.application import CustomerAgent
        state, _, index = selection_state(); state["identity"]["customer_id"] = "other"
        result, blocked = CustomerAgent().assess_candidates(state, index)
        self.assertEqual(result["code"], "invalid_state")
        self.assertIn("session_block", blocked)

    def test_completed_full_product_reread_removes_old_variants_instead_of_merging(self):
        state, api, index = selection_state()
        api.products["product_mug"]["items"] = [i for i in api.products["product_mug"]["items"] if i["item_id"] != "item_red"]
        state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "new-membership")
        self.assertEqual(assess_candidates(state, index)[0]["code"], "no_eligible_candidates")

    def test_complete_reread_can_resolve_prior_failure_without_fabricating_consent(self):
        state, api, index = selection_state()
        call = ToolAction("failed-once", "get_product", bind_arguments("get_product", {"product_id": "product_mug"}, state))
        record_decision(state, Decision(calls=(call,)))
        _, state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "failed", True),)), state)
        self.assertEqual(assess_candidates(state, index)[0]["code"], "product_read_required")
        state = accept_read(state, api, "get_product", {"product_id": "product_mug"}, "resolved-product")
        result, assessed = assess_candidates(state, index)
        self.assertEqual(result["code"], "candidate_selected")
        self.assertEqual(assessed["proposals"], [])

    def test_handoff_request_blocks_selection_even_with_complete_facts(self):
        state, _, _ = selection_state()
        _, state = advance(TurnInput("user", "Please transfer me to a human agent."), state)
        index = next(i for i in range(len(state["history"])-1, -1, -1) if state["history"][i]["role"] == "user")
        self.assertEqual(assess_candidates(state, index)[0]["code"], "handoff_blocks_selection")


if __name__ == "__main__":
    unittest.main()
