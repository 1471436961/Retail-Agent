"""M3.1 pure-rule decisions over synthetic teaching-shaped facts."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.domain.catalog import resolve_replacements, resolve_return_items, return_refund_basis
from support_agent.domain.orders import ORDER_ACTIONS, ORDER_STATUSES, capability_rule, order_state_rule
from support_agent.domain.policies import (cancellation_reason_rule, cancellation_refund_basis,
    refund_timing_rule, return_destination_rule, settlement_method_rule)
from support_agent.domain.rules import allow, result


def originals():
    return [{"item_id": "old_blue", "product_id": "product_mug", "name": "Example mug",
             "options": {"color": "blue", "size": "large"}, "price": 12.5}]


def catalog():
    return [{"product_id": "product_mug", "name": "Example mug", "items": [
        {"item_id": "new_red", "options": {"color": "red", "size": "large"}, "available": True, "price": 20.0},
        {"item_id": "new_green", "options": {"color": "green", "size": "large"}, "available": True, "price": 10.0}]}]


def replacements(target="new_red"):
    return [{"existing_item_id": "old_blue", "replacement_item_id": target}]


def payment_methods():
    return [{"id": "card_old", "source": "credit_card", "brand": "visa", "last_four": "0001"},
            {"id": "card_other", "source": "credit_card", "brand": "visa", "last_four": "0002"},
            {"id": "paypal_other", "source": "paypal"},
            {"id": "gift_old", "source": "gift_card", "balance": 7.5}]


def charge(method="card_old", amount=12.5, kind="payment"):
    return {"transaction_type": kind, "amount": amount, "payment_method_id": method}


class OrderRuleTests(unittest.TestCase):
    def test_all_exact_states_and_actions_follow_the_permission_matrix(self):
        matrix = {"pending": {"shipping_address", "payment_method", "cancel", "modify_items"},
                  "delivered": {"return", "exchange"}}
        for state in ORDER_STATUSES:
            for action in ORDER_ACTIONS:
                with self.subTest(state=state, action=action):
                    record = {"order_id": "#SYNTHETIC", "customer_id": "customer_a", "status": state}
                    decision = order_state_rule(record, action)
                    self.assertEqual(decision["decision"], "allow" if action in matrix.get(state, set()) else "deny")
                    state_codes = {"pending (items modified)": "items_modified_lock", "processed": "order_processed",
                                   "cancelled": "order_cancelled", "return requested": "return_exchange_already_requested",
                                   "exchange requested": "return_exchange_already_requested"}
                    expected = "state_eligible" if action in matrix.get(state, set()) else state_codes.get(state, "action_not_allowed_in_state")
                    self.assertEqual(decision["code"], expected)
                    if expected == "state_eligible":
                        self.assertEqual(decision["details"], {"order_id": "#SYNTHETIC", "status": state, "action": action})
                    self.assertTrue(decision["rules"])

    def test_modified_pending_and_submitted_requests_never_unlock_other_actions(self):
        for status, code in (("pending (items modified)", "items_modified_lock"),
                ("return requested", "return_exchange_already_requested"),
                ("exchange requested", "return_exchange_already_requested")):
            for action in ORDER_ACTIONS:
                result = order_state_rule({"order_id": "o", "customer_id": "c", "status": status}, action)
                self.assertEqual((result["decision"], result["code"]), ("deny", code))

    def test_unknown_and_malformed_states_require_investigation_without_coercion(self):
        for status in (None, True, [], "shipped", "Pending", " pending", "delivered "):
            with self.subTest(status=status):
                decision = order_state_rule({"order_id": "o", "customer_id": "c", "status": status}, "return")
                self.assertEqual(decision["code"], "unknown_order_state")
                self.assertEqual(decision["decision"], "needs_information")
        self.assertEqual(order_state_rule({}, "cancel")["code"], "order_facts_required")

    def test_operation_receipts_conflicting_with_status_stop_eligibility(self):
        for field in ("cancellation", "exchange", "return_request"):
            for receipt in ({}, [], "submitted"):
                result = order_state_rule({"order_id": "o", "customer_id": "c", "status": "pending", field: receipt}, "cancel")
                self.assertEqual(result["code"], "contradictory_order_facts")
                self.assertNotEqual(result["decision"], "allow")

    def test_tracking_only_does_not_change_exact_state_eligibility(self):
        # This checks non-inference only, not the future pre-write-refresh U6 guard.
        for status in ORDER_STATUSES:
            order = {"order_id": "o", "customer_id": "c", "status": status}
            tracked = {**order, "fulfillments": [{"item_ids": ["old_blue"], "tracking_id": ["TRACK"]}]}
            for action in ORDER_ACTIONS:
                with self.subTest(status=status, action=action):
                    self.assertEqual(order_state_rule(tracked, action), order_state_rule(order, action))
        self.assertEqual(order_state_rule({**tracked, "status": "pending"}, "cancel")["code"], "state_eligible")
        self.assertEqual(order_state_rule({**tracked, "status": "pending"}, "return")["code"], "action_not_allowed_in_state")

    def test_unlisted_capabilities_and_separate_records_are_explicitly_rejected(self):
        for action in ("change_quantity", "split_order", "update_email", "add_payment_method", "place_order", "restore_order", "partial_cancel", [], None):
            self.assertEqual(capability_rule(action)["decision"], "deny")
        order = {"order_id": "o", "customer_id": "c", "status": "cancelled"}
        self.assertEqual(capability_rule("default_shipping_address")["decision"], "allow")
        self.assertEqual(capability_rule("transfer")["code"], "supported_action")
        self.assertEqual(order_state_rule(order, "default_shipping_address")["code"], "not_order_action")

    def test_decisions_are_owned_json_facts_and_do_not_mutate_inputs(self):
        details = {"ids": ["a"]}
        decision = allow("example", "Eligibility only", "BN-01", details=details)
        details["ids"].append("b")
        self.assertEqual(decision, {"decision": "allow", "code": "example", "message": "Eligibility only",
                                    "rules": ["BN-01"], "details": {"ids": ["a"]}})
        decision["details"]["ids"].append("c")
        self.assertEqual(details, {"ids": ["a", "b"]})

    def test_result_rejects_invalid_decisions_and_details_without_silent_defaults(self):
        self.assertEqual(allow("c", "m", details=None)["details"], {})
        for details in (False, 0, [], "", "wrong"):
            with self.subTest(details=details), self.assertRaises(TypeError):
                allow("c", "m", details=details)
        for decision in ([], None, "invalid"):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                result(decision, "c", "m")
        with self.assertRaises(TypeError):
            allow("c", "m", details={"value": object()})
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                allow("c", "m", details={"value": value})

    def test_submitted_request_reasons_identify_the_requested_action(self):
        for status in ("return requested", "exchange requested"):
            for action in ("shipping_address", "payment_method", "cancel", "modify_items"):
                decision = order_state_rule({"order_id": "o", "customer_id": "c", "status": status}, action)
                self.assertIn(action, decision["message"])
                self.assertIn(status, decision["message"])
                self.assertEqual(decision["details"], {"status": status, "action": action})
            self.assertIn("cannot be appended", order_state_rule({"order_id": "o", "customer_id": "c", "status": status}, "return")["message"])


class SpecificationRuleTests(unittest.TestCase):
    def resolve(self, items=None, pairs=None, products=None, changes=None):
        return resolve_replacements(items if items is not None else originals(),
            pairs if pairs is not None else replacements(), products if products is not None else catalog(),
            requested_options=changes if changes is not None else [{"color": "red"}])

    def test_catalog_item_membership_comes_from_product_envelope(self):
        products = catalog()
        result = self.resolve(products=products)
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["details"]["price_pairs"], [[12.5, 20.0]])
        self.assertEqual(result["details"]["price_difference"], 7.5)
        self.assertFalse(result["details"]["settlement_verified"])

    def test_cross_product_and_unavailable_variants_are_rejected(self):
        products = catalog()
        products[0]["product_id"] = "product_other"
        self.assertEqual(self.resolve(products=products)["code"], "different_product")
        products = catalog()
        products[0]["items"][0]["available"] = False
        self.assertEqual(self.resolve(products=products)["code"], "variant_unavailable")

    def test_unrequested_attributes_and_explicit_hard_constraints_are_preserved(self):
        products = catalog()
        for options in ({"color": "red", "size": "small"}, {"color": "black", "size": "large"}, {"color": "red"}):
            products[0]["items"][0]["options"] = options
            self.assertEqual(self.resolve(products=products)["code"], "specification_mismatch")
        result = resolve_replacements(originals(), replacements(), catalog())
        self.assertEqual(result["code"], "requested_options_required")
        self.assertEqual(self.resolve(changes=[{"material": "wood"}])["code"], "unknown_option")

    def test_duplicate_original_units_keep_two_distinct_targets_and_request_order(self):
        items = originals() * 2
        pairs = replacements() + replacements("new_green")
        products = catalog()
        snapshot = deepcopy((items, pairs, products))
        result = self.resolve(items=items, pairs=pairs, products=products, changes=[{"color": "red"}, {"color": "green"}])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["details"]["replacements"], pairs)
        self.assertEqual(result["details"]["price_pairs"], [[12.5, 20.0], [12.5, 10.0]])
        self.assertEqual(result["details"]["price_difference"], 5.0)
        self.assertEqual((items, pairs, products), snapshot)
        result["details"]["replacements"][0]["replacement_item_id"] = "mutated"
        self.assertEqual((items, pairs, products), snapshot)

    def test_quantity_unknown_original_and_undocumented_selectors_do_not_pass(self):
        self.assertEqual(self.resolve(pairs=replacements() * 2, changes=[{"color": "red"}] * 2)["code"], "quantity_exceeds_order")
        self.assertEqual(self.resolve(pairs=[{"existing_item_id": "missing", "replacement_item_id": "new_red"}])["code"], "item_not_in_order")
        for key in ("quantity", "order_line_id", "occurrence"):
            pair = replacements()
            pair[0][key] = 1
            decision = self.resolve(pairs=pair)
            self.assertEqual(decision["decision"], "deny")
            if key == "quantity":
                self.assertEqual(decision["code"], "quantity_change_unsupported")
                self.assertNotIn("input_error", decision["details"])
            else:
                self.assertEqual(decision["code"], "invalid_replacement_list")
                self.assertTrue(decision["details"]["input_error"])
        self.assertEqual(self.resolve(pairs=[])["code"], "empty_item_selection")

    def test_differing_same_id_instances_are_not_priced_or_silently_selected(self):
        for field, value in (("price", 9.0), ("options", {"color": "blue", "size": "small"}), ("product_id", "other")):
            items = originals() + deepcopy(originals())
            items[1][field] = value
            self.assertEqual(self.resolve(items=items)["code"], "instance_selection_unavailable")
            self.assertEqual(resolve_return_items(items, ["old_blue"])["code"], "instance_selection_unavailable")

    def test_incomplete_malformed_or_duplicate_catalog_is_not_pricing_evidence(self):
        for field, value in (("price", "20"), ("price", True), ("price", float("inf")), ("price", -1),
                             ("available", "true"), ("options", {"color": True})):
            products = catalog()
            products[0]["items"][0][field] = value
            self.assertEqual(self.resolve(products=products)["code"], "catalog_facts_required")
        products = catalog()
        products[0]["items"].append(deepcopy(products[0]["items"][0]))
        self.assertEqual(self.resolve(products=products)["code"], "catalog_facts_required")
        self.assertEqual(self.resolve(products=catalog() * 2)["code"], "catalog_facts_required")
        self.assertEqual(self.resolve(products=[])["code"], "target_variant_required")
        for products in (False, [None], [{}], [{**catalog()[0], "product_id": ""}],
                         [{**catalog()[0], "name": 1}], [{**catalog()[0], "items": {}}]):
            with self.subTest(products=products):
                self.assertEqual(self.resolve(products=products)["code"], "catalog_facts_required")

    def test_unchanged_and_sequential_collision_variants_require_a_safe_list(self):
        products = catalog()
        products[0]["items"].append({"item_id": "old_blue", "options": originals()[0]["options"], "available": True, "price": 12.5})
        self.assertEqual(self.resolve(pairs=replacements("old_blue"), products=products)["code"], "unchanged_variant")
        items = originals() + [{**originals()[0], "item_id": "new_red", "options": {"color": "red", "size": "large"}}]
        pairs = replacements() + [{"existing_item_id": "new_red", "replacement_item_id": "new_green"}]
        self.assertEqual(self.resolve(items=items, pairs=pairs, changes=[{"color": "red"}, {"color": "green"}])["code"], "sequential_match_ambiguous")

    def test_resolved_prices_use_original_precision_and_only_final_difference_rounding(self):
        items = originals() * 2
        for item in items:
            item["price"] = 0.0
        products = catalog()
        products[0]["items"][0]["price"] = 0.014
        result = self.resolve(items=items, pairs=replacements() * 2, products=products, changes=[{"color": "red"}] * 2)
        self.assertEqual(result["details"]["price_difference"], 0.03)
        self.assertEqual(result["details"]["price_pairs"], [[0.0, 0.014], [0.0, 0.014]])
        items = originals()
        items[0]["price"] = 0.0
        products[0]["items"][0]["price"] = 2.675
        self.assertEqual(self.resolve(items=items, products=products)["details"]["price_difference"], 2.67)

    def test_return_selection_preserves_original_prices_counts_and_ownership(self):
        items = originals() * 2
        result = resolve_return_items(items, ["old_blue", "old_blue"])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual([i["price"] for i in result["details"]["items"]], [12.5, 12.5])
        self.assertEqual(result["details"]["item_ids"], ["old_blue", "old_blue"])
        self.assertEqual(set(result["details"]), {"items", "item_ids"})
        result["details"]["items"][0]["price"] = 99
        self.assertEqual(items[0]["price"], 12.5)
        self.assertEqual(resolve_return_items(items, ["old_blue"] * 3)["code"], "quantity_exceeds_order")

    def test_return_estimate_sums_original_occurrences_without_claiming_settlement(self):
        items = originals() * 2
        for item in items:
            item["price"] = 0.014
        result = return_refund_basis(items, ["old_blue", "old_blue"])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["code"], "original_price_refund_estimate")
        self.assertEqual([i["price"] for i in result["details"]["items"]], [0.014, 0.014])
        self.assertEqual(result["details"]["aggregate_amount"], 0.03)
        self.assertTrue(result["details"]["amount_is_estimate"])
        self.assertFalse(result["details"]["aggregation_contract_verified"])
        self.assertFalse(result["details"]["settlement_verified"])
        result["details"]["items"][0]["price"] = 999
        self.assertEqual(items[0]["price"], 0.014)
        self.assertEqual(return_refund_basis(items, ["old_blue"] * 3)["decision"], "deny")

    def test_invalid_original_amounts_are_never_converted_into_quotes(self):
        for value in (True, "12.5", float("nan"), -1, 10 ** 400):
            items = originals()
            items[0]["price"] = value
            self.assertEqual(self.resolve(items=items)["decision"], "needs_information")

    def test_missing_selection_differs_from_malformed_candidate_arguments(self):
        missing = resolve_replacements(originals(), None, catalog())
        self.assertEqual((missing["decision"], missing["code"]), ("needs_information", "replacement_list_required"))
        self.assertEqual(resolve_return_items(originals(), None)["decision"], "needs_information")
        for ids in ("old_blue", 1, [1], [""]):
            decision = resolve_return_items(originals(), ids)
            self.assertEqual((decision["decision"], decision["code"]), ("deny", "invalid_item_ids"))
            self.assertTrue(decision["details"]["input_error"])
        for pairs in ({}, [1], [{"existing_item_id": "old_blue"}], [{"existing_item_id": 1, "replacement_item_id": "new_red"}]):
            decision = resolve_replacements(originals(), pairs, catalog())
            self.assertEqual(decision["code"], "invalid_replacement_list")
            self.assertTrue(decision["details"]["input_error"])
        for changes in ({}, [], [None], [{"color": True}]):
            decision = resolve_replacements(originals(), replacements(), catalog(), requested_options=changes)
            self.assertEqual(decision["code"], "invalid_requested_options")
            self.assertTrue(decision["details"]["input_error"])


class PaymentRuleTests(unittest.TestCase):
    def test_one_different_saved_switch_method_and_full_gift_card_coverage(self):
        methods = payment_methods()
        for amount, decision in ((7.5, "allow"), (7.51, "deny")):
            result = settlement_method_rule("payment_method", methods, "gift_old", amount, current_payment_method_id="card_old")
            self.assertEqual(result["decision"], decision)
        self.assertEqual(settlement_method_rule("payment_method", methods, "card_old", 7.5, current_payment_method_id="card_old")["code"], "same_payment_method")
        self.assertEqual(settlement_method_rule("payment_method", methods, "card_other", 7.5)["code"], "current_payment_method_required")

    def test_item_change_gift_card_requires_coverage_only_for_a_charge(self):
        methods = payment_methods()
        for action in ("modify_items", "exchange"):
            for amount, decision in ((7.5, "allow"), (7.51, "deny"), (-50, "allow"), (0, "allow")):
                with self.subTest(action=action, amount=amount):
                    self.assertEqual(settlement_method_rule(action, methods, "gift_old", amount)["decision"], decision)

    def test_negative_exchange_and_modification_can_use_another_saved_card(self):
        for action in ("modify_items", "exchange"):
            result = settlement_method_rule(action, payment_methods(), "card_other", -7.5)
            self.assertEqual(result["decision"], "allow")
            self.assertEqual(result["details"]["direction"], "refund")
            self.assertFalse(result["details"]["settlement_verified"])
        self.assertEqual(return_destination_rule(payment_methods(), [charge()], "card_other")["decision"], "deny")

    def test_zero_difference_still_requires_a_saved_method_and_split_is_denied(self):
        for action in ("modify_items", "exchange"):
            self.assertEqual(settlement_method_rule(action, payment_methods(), "", 0)["code"], "payment_method_required")
            self.assertEqual(settlement_method_rule(action, payment_methods(), "new_card", 0)["decision"], "deny")
        for methods in (["card_old", "card_other"], ("card_old", "card_other")):
            self.assertEqual(settlement_method_rule("exchange", payment_methods(), methods, 5)["code"], "single_method_required")

    def test_all_saved_methods_are_considered_without_a_five_card_cap(self):
        methods = payment_methods() + [{"id": f"paypal_{i}", "source": "paypal"} for i in range(8)]
        self.assertEqual(settlement_method_rule("exchange", methods, "paypal_7", 100)["decision"], "allow")

    def test_bad_or_duplicate_methods_and_unknown_amounts_stop_settlement_checks(self):
        for amount in (None, True, "7.5", float("nan"), float("inf"), 10 ** 400):
            self.assertEqual(settlement_method_rule("exchange", payment_methods(), "card_other", amount)["code"],
                             "amount_required" if amount is None else "invalid_amount")
        for balance in (True, "7.5", -1, float("inf")):
            methods = payment_methods()
            methods[-1]["balance"] = balance
            self.assertEqual(settlement_method_rule("exchange", methods, "gift_old", 1)["code"], "payment_facts_required")
        self.assertEqual(settlement_method_rule("exchange", payment_methods() * 2, "card_other", 1)["code"], "payment_facts_required")
        self.assertEqual(settlement_method_rule("return", payment_methods(), "card_other", -1)["decision"], "deny")
        self.assertEqual(settlement_method_rule("payment_method", payment_methods(), "card_other", -1, current_payment_method_id="card_old")["code"], "invalid_order_amount")

    def test_return_original_method_is_derived_only_from_original_charges(self):
        payments = [charge(), charge("card_other", 1, "refund")]
        self.assertEqual(return_destination_rule(payment_methods(), payments, "card_old")["decision"], "allow")
        self.assertEqual(return_destination_rule(payment_methods(), payments, "card_other")["decision"], "deny")
        self.assertEqual(return_destination_rule(payment_methods(), payments, "paypal_other")["decision"], "deny")
        self.assertEqual(return_destination_rule(payment_methods(), payments, "new_gift")["decision"], "deny")

    def test_supplied_opening_snapshot_limits_gift_candidates(self):
        methods = payment_methods()
        self.assertEqual(return_destination_rule(methods, [charge()], "gift_old")["code"], "opening_snapshot_required")
        self.assertEqual(return_destination_rule(methods, [charge()], "gift_old", opening_payment_methods=methods)["decision"], "allow")
        self.assertEqual(return_destination_rule(methods, [charge()], "gift_old", opening_payment_methods=methods[:-1])["code"], "gift_card_not_eligible_at_opening")
        methods.append({"id": "gift_new", "source": "gift_card", "balance": 0})
        self.assertEqual(return_destination_rule(methods, [charge()], "gift_new", opening_payment_methods=payment_methods())["decision"], "deny")

    def test_return_choice_is_not_auto_selected_even_when_only_one_candidate_exists(self):
        result = return_destination_rule(payment_methods(), [charge()], "")
        self.assertEqual(result["decision"], "needs_information")
        self.assertEqual(result["details"]["candidate_ids"], ["card_old"])
        result = return_destination_rule(payment_methods(), [charge()], "", opening_payment_methods=payment_methods())
        self.assertEqual(result["details"]["candidate_ids"], ["card_old", "gift_old"])
        repeated = return_destination_rule(payment_methods(), [charge(), charge(), charge("card_other"), charge("paypal_other", kind="refund")], "")
        self.assertEqual(repeated["details"]["candidate_ids"], ["card_old", "card_other"])

    def test_cancellation_basis_never_nets_groups_duplicates_or_claims_arrival(self):
        payments = [charge(amount=10), charge(amount=3), charge(amount=1, kind="refund")]
        snapshot = deepcopy(payments)
        result = cancellation_refund_basis(payments)
        self.assertEqual(result["decision"], "allow")
        self.assertEqual([p["amount"] for p in result["details"]["charges"]], [10, 3])
        self.assertEqual(result["details"]["recorded_refunds"], [payments[2]])
        self.assertIsNone(result["details"]["aggregate_amount"])
        self.assertFalse(result["details"]["aggregation_contract_verified"])
        self.assertFalse(result["details"]["settlement_verified"])
        result["details"]["charges"][0]["amount"] = 99
        self.assertEqual(payments, snapshot)

    def test_missing_charges_and_malformed_histories_do_not_default_to_zero(self):
        for records in (None, [], [charge(kind="refund")], [charge(amount="12.5")], [charge(amount=True)],
                        [{**charge(), "timestamp": "invented"}], [charge(kind="charge")]):
            self.assertEqual(cancellation_refund_basis(records)["decision"], "needs_information")
            self.assertNotEqual(return_destination_rule(payment_methods(), records, "card_old")["decision"], "allow")

    def test_refund_channel_policy_is_distinct_from_actual_settlement(self):
        for source, timing in (("gift_card", "immediate"), ("credit_card", "3-6 business days"), ("paypal", "3-6 business days")):
            result = refund_timing_rule(source)
            self.assertEqual(result["details"]["timing"], timing)
            self.assertFalse(result["details"]["settlement_verified"])
        for source in ("check", None, [], True):
            self.assertEqual(refund_timing_rule(source)["decision"], "needs_information")

    def test_clear_reason_aliases_are_normalized_without_granting_consent(self):
        for text, reason in (("I changed my mind.", "no longer needed"), ("误下单", "ordered by mistake"),
                             ("Ordered by mistake", "ordered by mistake")):
            result = cancellation_reason_rule(text)
            self.assertEqual(result["details"], {"reason": reason})
            self.assertNotIn("confirmed", result["details"])
        for text in ("price is too high", "late delivery", "I did not order by mistake", "maybe", "", None):
            self.assertEqual(cancellation_reason_rule(text)["decision"], "needs_information")

    def test_settlement_rule_preserves_resolved_precision_without_coercion(self):
        for amount, direction in ((1.125, "charge"), (-1.125, "refund"), (0, "zero")):
            decision = settlement_method_rule("exchange", payment_methods(), "card_other", amount)
            self.assertEqual(decision["decision"], "allow")
            self.assertEqual(decision["details"]["amount"], amount)
            self.assertEqual(decision["details"]["direction"], direction)
        for value in (True, "1.125", float("nan"), float("inf"), 10 ** 400):
            decision = settlement_method_rule("exchange", payment_methods(), "card_other", value)
            self.assertEqual(decision["code"], "invalid_amount")
            self.assertTrue(decision["details"]["input_error"])

    def test_candidate_input_errors_are_distinct_from_missing_business_information(self):
        for method_id in (1, True, {}, ["card_old"]):
            decision = return_destination_rule(payment_methods(), [charge()], method_id)
            self.assertEqual((decision["decision"], decision["code"]), ("deny", "invalid_payment_method_id"))
            self.assertTrue(decision["details"]["input_error"])
        for method_id in (1, True, {}):
            decision = settlement_method_rule("exchange", payment_methods(), method_id, 1)
            self.assertTrue(decision["details"]["input_error"])
        self.assertEqual(return_destination_rule(payment_methods(), [charge()], None)["decision"], "needs_information")
        self.assertEqual(settlement_method_rule("exchange", payment_methods(), None, 1)["decision"], "needs_information")
        self.assertEqual(settlement_method_rule("payment_method", payment_methods(), "card_other", 1, current_payment_method_id=[])["code"], "invalid_current_payment_method_id")
        for function in (capability_rule, cancellation_reason_rule):
            self.assertTrue(function([])["details"]["input_error"])
        self.assertTrue(settlement_method_rule([], payment_methods(), "card_other", 1)["details"]["input_error"])

    def test_saved_method_schema_rejects_extra_and_missing_fields_for_each_source(self):
        for index in range(len(payment_methods())):
            methods = payment_methods()
            methods[index]["extra"] = "unsupported"
            self.assertEqual(settlement_method_rule("exchange", methods, "card_other", 1)["code"], "payment_facts_required")
            self.assertEqual(return_destination_rule(methods, [charge()], "card_old")["code"], "refund_destination_facts_required")
        for index, field in ((0, "brand"), (0, "last_four"), (2, "source"), (3, "balance")):
            methods = payment_methods()
            del methods[index][field]
            self.assertEqual(settlement_method_rule("exchange", methods, "card_other", 1)["code"], "payment_facts_required")

    def test_static_upstream_history_loop_differs_from_rf01_charge_basis(self):
        # Model the inspected upstream loop's row selection only. No SDK write is executed.
        payments = [charge(amount=10), charge(amount=3), charge(amount=1, kind="refund")]
        snapshot = deepcopy(payments)
        upstream_rows = [(p["payment_method_id"], p["amount"]) for p in payments]
        decision = cancellation_refund_basis(payments)
        project_rows = [(p["payment_method_id"], p["amount"]) for p in decision["details"]["charges"]]
        self.assertEqual(upstream_rows, [("card_old", 10), ("card_old", 3), ("card_old", 1)])
        self.assertEqual(project_rows, [("card_old", 10), ("card_old", 3)])
        self.assertNotEqual(project_rows, upstream_rows)
        self.assertEqual(decision["details"]["recorded_refunds"], [charge(amount=1, kind="refund")])
        self.assertEqual(payments, snapshot)


if __name__ == "__main__":
    unittest.main()
