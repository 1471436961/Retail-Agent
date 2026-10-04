"""M0-M3 closure against concrete session adapters, never real services."""
import json
import unittest
from decimal import Decimal, ROUND_HALF_EVEN
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import unquote
from unittest.mock import patch

from test_m3_proposals import verified_state, specification, agree, accept_read
from test_m3_writes import confirmed, FakeRuntime, writes
from fakes import FakeResponse
from fakes import FakeClientAPI
from support_agent.adapters.write_runtime import SessionClaims, SessionWriteRuntime
from support_agent.domain.catalog import return_refund_basis
from support_agent.proposals import InvalidProposal, present_proposal, confirmation_matches, _scope_facts
from support_agent.state import InvalidState, initial_state, clone_state
from support_agent.write_session import execute_operation, reconcile_operation, claim_identity, WriteClaimConflict


def return_spec(copies=1, destination="card_a"):
    return {"action": "return", "target": {"customer_id": "customer_a", "order_id": "#TEST1"},
            "parameters": {"item_ids": ["item_blue"] * copies, "refund_payment_method_id": destination},
            "amount": {"kind": "estimated_refund", "value": 12.5 * copies,
                       "estimate_method": "original_prices_decimal_sum_half_up_cents"}}


def transport(api, *, unknown=False):
    """Contract fake behind the actual endpoint adapter; reads still use M2."""
    original = api.request
    api.context = SimpleNamespace(conversation_id="synthetic-session")
    sends = []
    def request(method, path, body=None):
        if method == "GET" or path == "/v1/customers/search":
            return original(method, path, body)
        sends.append((method, path, deepcopy(body)))
        if unknown:
            raise TimeoutError("synthetic unknown")
        identifier, endpoint = unquote(path.split("/")[-2]), path.split("/")[-1]
        order = api.orders.get(identifier)
        if endpoint == "default-shipping-address":
            result = {"customer_id": identifier, "default_shipping_address": deepcopy(body)}
            api.customers[identifier].update(deepcopy(result))
        elif endpoint == "shipping-address":
            result = {"order_id": identifier, "shipping_address": deepcopy(body)}
            order.update(deepcopy(result))
        elif endpoint == "returns":
            result = {"order_id": identifier, "status": "return requested",
                      "return_request": {**deepcopy(body), "item_ids": sorted(body["item_ids"])}}
            order.update(deepcopy(result))
        elif endpoint == "cancellations":
            result = {"order_id": identifier, "status": "cancelled", "cancellation": deepcopy(body),
                      "payments": order["payments"] + [{**p, "transaction_type": "refund"} for p in order["payments"]]}
            order.update(deepcopy(result))
        elif endpoint == "payment-method":
            old = order["payments"][0]
            result = {"order_id": identifier, "payments": order["payments"] + [
                {**old, "payment_method_id": body["payment_method_id"]}, {**old, "transaction_type": "refund"}]}
            order.update(deepcopy(result))
        elif endpoint in {"item-modifications", "exchanges"}:
            if endpoint == "exchanges":
                result = {"order_id": identifier, "status": "exchange requested",
                          "exchange": {**deepcopy(body), "price_difference": -1.12}}
            else:
                items = deepcopy(order["items"])
                for pair in body["replacements"]:
                    original_item = next(i for i in items if i["item_id"] == pair["existing_item_id"])
                    variant = next(v for v in api.products[original_item["product_id"]]["items"] if v["item_id"] == pair["replacement_item_id"])
                    original_item.update(item_id=variant["item_id"], price=variant["price"], options=deepcopy(variant["options"]))
                result = {"order_id": identifier, "status": "pending (items modified)", "items": items,
                          "payments": order["payments"] + [{"transaction_type":"refund", "amount":1.12,
                                                            "payment_method_id":body["payment_method_id"]}]}
            order.update(deepcopy(result))
        else:
            raise AssertionError("Unexpected endpoint in this fixture")
        return FakeResponse(200, result)
    api.request = request
    return sends


class ReturnCompletionTests(unittest.TestCase):
    def test_estimate_overflow_is_controlled_and_nonfinite_prices_cannot_quote(self):
        _, api = verified_state(item_copies=2)
        items = deepcopy(api.orders["#TEST1"]["items"])
        for item in items: item["price"] = 1e308
        self.assertEqual(return_refund_basis(items, ["item_blue"] * 2)["code"], "refund_estimate_unrepresentable")
        for price in (True, float("nan"), "12.5"):
            items[0]["price"] = price
            self.assertEqual(return_refund_basis(items, ["item_blue"])["code"], "original_items_required")

    def test_gift_card_in_earliest_verified_profile_is_an_eligible_chosen_destination(self):
        api = FakeClientAPI()
        api.customers["customer_a"]["payment_methods"].append({"id":"opening_gift", "source":"gift_card", "balance":0})
        with patch("test_m3_proposals.FakeClientAPI", return_value=api):
            state, api = verified_state(status="delivered")
        spec = return_spec(destination="opening_gift")
        _, state = present_proposal(state, spec); _, state = agree(state)
        sends = transport(api)
        result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(sends[0][2]["refund_payment_method_id"], "opening_gift")

    def test_display_estimate_uses_decimal_prices_occurrences_and_half_up(self):
        state, _ = verified_state(item_copies=2)
        items = deepcopy(_scope_facts(
            state["history"], specification(), state_only=True)["order"]["items"])
        for item in items:
            item["price"] = 0.005
        estimate = return_refund_basis(items, ["item_blue"] * 2)
        self.assertEqual(estimate["details"]["aggregate_amount"], 0.01)
        self.assertEqual(estimate["details"]["exact_price_sum"], "0.010")
        self.assertFalse(estimate["details"]["settlement_verified"])
        self.assertEqual(items[0]["price"], 0.005)

    def test_single_unit_midpoints_distinguish_display_half_up_from_other_rounding(self):
        state, _ = verified_state()
        items = deepcopy(_scope_facts(state["history"], specification(), state_only=True)["order"]["items"])
        for price, expected in ((0.005, 0.01), (0.015, 0.02), (1.005, 1.01)):
            with self.subTest(price=price):
                items[0]["price"] = price
                result = return_refund_basis(items, ["item_blue"])["details"]
                self.assertEqual(result["aggregate_amount"], expected)
                self.assertEqual(result["exact_price_sum"], str(price))
                self.assertEqual(result["estimate_method"], "original_prices_decimal_sum_half_up_cents")
                self.assertTrue(result["amount_is_estimate"])
                self.assertFalse(result["aggregation_contract_verified"])
                self.assertFalse(result["settlement_verified"])
        items[0]["price"] = 0.005
        estimate = return_refund_basis(items, ["item_blue"])["details"]["aggregate_amount"]
        self.assertNotEqual(estimate, float(Decimal("0.005").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)))
        items[0]["price"] = 0.015
        self.assertNotEqual(return_refund_basis(items, ["item_blue"])["details"]["aggregate_amount"], round(0.015, 2))

    def test_original_destination_return_recap_confirmation_send_readback_and_restore(self):
        state, api = verified_state(status="delivered", item_copies=2)
        spec = return_spec(2)
        message, state = present_proposal(state, spec)
        self.assertIn("Estimated original-price refund: 25.00 (decimal sum, half-up cents).", message.text.splitlines())
        self.assertIn("not a settlement guarantee", message.text)
        _, state = agree(state)
        self.assertTrue(confirmation_matches(state, 1, spec))
        sends = transport(api)
        result, written = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(sends, [("POST", "/v1/orders/%23TEST1/returns", spec["parameters"])])
        self.assertNotIn("amount", sends[0][2])
        self.assertEqual(writes(written)[0]["status"], "succeeded")
        self.assertEqual(initial_state(written["history"])["operations"], written["operations"])
        self.assertEqual(clone_state(written), written)

    def test_wrong_estimate_and_unrelated_card_do_not_form_proposals(self):
        state, _ = verified_state(status="delivered")
        for change in ("value", "destination"):
            spec = return_spec()
            if change == "value": spec["amount"]["value"] = 99
            else: spec["parameters"]["refund_payment_method_id"] = "card_other"
            with self.assertRaises(InvalidProposal): present_proposal(state, spec)

    def test_late_gift_card_cannot_backfill_opening_eligibility(self):
        state, api = verified_state(status="delivered")
        _, state = agree(state, "Please start a return.")
        api.customers["customer_a"]["payment_methods"].append({"id": "late_gift", "source": "gift_card", "balance": 0})
        from support_agent.write_session import _read
        _read(state, api, "read_customer_profile", {}, "late-profile")
        with self.assertRaises(InvalidProposal): present_proposal(state, return_spec(destination="late_gift"))
        _, original = present_proposal(state, return_spec())
        self.assertEqual(original["proposals"][-1]["spec"]["parameters"]["refund_payment_method_id"], "card_a")

    def test_profile_before_return_opening_can_include_a_card_added_after_verification(self):
        state, api = verified_state(status="delivered")
        api.customers["customer_a"]["payment_methods"].append({"id":"before_opening_gift", "source":"gift_card", "balance":0})
        from support_agent.write_session import _read
        _read(state, api, "read_customer_profile", {}, "before-opening-profile")
        _, state = agree(state, "Please start a return.")
        spec = return_spec(destination="before_opening_gift")
        _, state = present_proposal(state, spec); _, state = agree(state)
        sends = transport(api)
        result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(sends[0][2]["refund_payment_method_id"], "before_opening_gift")

    def test_return_price_refresh_invalidates_consent_before_send(self):
        state, api = verified_state(status="delivered")
        spec = return_spec(); _, state = present_proposal(state, spec); _, state = agree(state)
        sends = transport(api); api.orders["#TEST1"]["items"][0]["price"] = 15
        result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "facts_unavailable")
        self.assertFalse(sends)


class SessionRuntimeTests(unittest.TestCase):
    def test_name_postal_identity_survives_mutated_default_postal_with_original_source(self):
        from support_agent.turns import advance
        from support_agent.protocol import TurnInput, ToolOutcome
        from support_agent.adapters.read_api import verify_customer
        _, api = verified_state()
        decision, state = advance(TurnInput(kind="user", content="customer_a; first_name: Ada; last_name: Example; postal_code: 90001"), initial_state())
        call = decision.calls[0]
        body = verify_customer(api, **call.arguments)
        _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id, json.dumps(body)),)), state)
        spec = specification("default_shipping_address")
        _, state = present_proposal(state, spec); _, state = agree(state)
        evidence = deepcopy(state["identity_evidence"])
        sends = transport(api)
        result, written = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(written["identity_evidence"], evidence)
        self.assertEqual(written["customer_record"]["default_shipping_address"]["postal_code"], "90002")
        self.assertEqual(initial_state(written["history"])["operations"], written["operations"])
        self.assertEqual(clone_state(written), written); self.assertEqual(len(sends), 1)

    def test_changed_postal_without_original_matching_lookup_cannot_preserve_identity(self):
        from support_agent.domain.identity import matches_session_customer, verification_inputs
        _, api = verified_state()
        record = deepcopy(api.customers["customer_a"])
        record["default_shipping_address"]["postal_code"] = "90002"
        proof = verification_inputs(first_name="Ada", last_name="Example", postal_code="90001")
        for history in ([], [{"role":"assistant", "content":"Identity verified for Ada Example 90001"}],
                        [{"role":"user", "content":"Ada Example 90001"}]):
            self.assertFalse(matches_session_customer(record, proof, "customer_a", history))

    def test_default_address_uses_customer_endpoint_and_does_not_change_order_address(self):
        state, api, spec = confirmed("default_shipping_address")
        before_order = deepcopy(api.orders["#TEST1"])
        sends = transport(api)
        result, written = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(sends[0][:2], ("PUT", "/v1/customers/customer_a/default-shipping-address"))
        self.assertEqual(api.orders["#TEST1"], before_order)
        self.assertEqual(initial_state(written["history"])["operations"], written["operations"])

    def test_modify_and_exchange_use_same_product_requested_options_and_exact_diff(self):
        for action in ("modify_items", "exchange"):
            state, api, spec = confirmed(action, "pending" if action == "modify_items" else "delivered")
            sends = transport(api)
            runtime = SessionWriteRuntime(api, claims=SessionClaims(), requested_options=[{"color":"red"}])
            result, written = execute_operation(state, 1, spec, runtime)
            self.assertEqual(result["code"], "write_verified")
            self.assertEqual(sends[0][0], "POST")
            self.assertEqual(sends[0][1].rsplit("/", 1)[-1], "item-modifications" if action == "modify_items" else "exchanges")
            self.assertEqual(sends[0][2], spec["parameters"])
            self.assertEqual(initial_state(written["history"])["operations"], written["operations"])

    def test_wrong_requested_options_block_before_claim_or_http_write(self):
        state, api, spec = confirmed("modify_items"); sends = transport(api)
        runtime = SessionWriteRuntime(api, claims=SessionClaims(), requested_options=[{"color":"green"}])
        result, written = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "specification_mismatch")
        self.assertFalse(sends); self.assertFalse(writes(written))

    def test_runtime_context_is_required_and_user_state_cannot_change_claim_scope(self):
        state, api, spec = confirmed()
        with self.assertRaises(ValueError): SessionWriteRuntime(api, claims=SessionClaims())
        sends = transport(api, unknown=True); store = SessionClaims()
        execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=store))
        stale = deepcopy(state); stale["conversation_id"] = "user-supplied-pretend-session"
        result, _ = execute_operation(stale, 1, spec, SessionWriteRuntime(api, claims=store))
        self.assertEqual(result["code"], "write_already_claimed")
        self.assertEqual(set(store.sessions), {"synthetic-session"}); self.assertEqual(len(sends), 1)

    def test_explicit_claim_success_is_required(self):
        for value in (False, None, 1, {"accepted": True}):
            state, api, spec = confirmed(); runtime = FakeRuntime(api)
            with patch.object(runtime, "claim_sent", return_value=value):
                result, _ = execute_operation(state, 1, spec, runtime)
            self.assertEqual(result["code"], "write_already_claimed")
            self.assertFalse(runtime.sends)

    def test_stale_snapshot_extra_history_and_new_runtime_share_stable_claim(self):
        state, api, spec = confirmed(); sends = transport(api, unknown=True); store = SessionClaims()
        result, original = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=store))
        self.assertEqual(result["code"], "write_result_unknown")
        stale = deepcopy(state); stale["history"].append({"role": "assistant", "content": "Unrelated explanation"})
        result, blocked = execute_operation(stale, 1, spec, SessionWriteRuntime(api, claims=store))
        self.assertEqual(result["code"], "write_already_claimed")
        self.assertNotEqual(writes(original)[0]["call_id"], writes(blocked)[0]["call_id"])
        self.assertEqual(claim_identity(original, writes(original)[0]["call_id"]), claim_identity(blocked, writes(blocked)[0]["call_id"]))
        self.assertEqual(len(sends), 1)

    def test_fresh_backend_replay_uses_fresh_store_and_same_request(self):
        requests = []
        for _ in range(2):
            state, api, spec = confirmed(); sends = transport(api)
            result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
            self.assertEqual(result["code"], "write_verified")
            requests.append(sends)
        self.assertEqual(requests[0], requests[1])

    def test_send_cannot_bypass_or_reuse_claim(self):
        state, api, spec = confirmed(); sends = transport(api); runtime = SessionWriteRuntime(api, claims=SessionClaims())
        with self.assertRaises(WriteClaimConflict): runtime.send(spec)
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "write_verified")
        with self.assertRaises(WriteClaimConflict): runtime.send(spec)
        self.assertEqual(len(sends), 1)

    def test_cancel_with_existing_refund_is_controlled_but_normal_charges_succeed(self):
        for prior_refund in (False, True):
            state, api = verified_state()
            if prior_refund:
                api.orders["#TEST1"]["payments"].append({"transaction_type": "refund", "amount": 1, "payment_method_id": "card_a"})
                state = accept_read(state, api, "get_order", {"order_id": "#TEST1"}, "updated-order")
            spec = specification("cancel"); _, state = present_proposal(state, spec); _, state = agree(state)
            sends = transport(api)
            result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
            self.assertEqual(result["code"], "cancellation_refund_history_review" if prior_refund else "write_verified")
            self.assertEqual(len(sends), 0 if prior_refund else 1)

    def test_payment_switch_uses_one_original_charge_and_rechecks_full_balance(self):
        state, api = verified_state(); api.orders["#TEST1"]["payments"] = [api.orders["#TEST1"]["payments"][0]]
        state = accept_read(state, api, "get_order", {"order_id": "#TEST1"}, "single-charge")
        spec = specification("payment_method"); spec["amount"].update(value=12.5, refund_rows=api.orders["#TEST1"]["payments"])
        _, state = present_proposal(state, spec); _, state = agree(state)
        sends = transport(api)
        result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(sends[0], ("PUT", "/v1/orders/%23TEST1/payment-method", {"payment_method_id": "card_other"}))

    def test_multicharge_payment_switch_does_not_invent_current_method(self):
        state, api, spec = confirmed("payment_method"); sends = transport(api)
        result, _ = execute_operation(state, 1, spec, SessionWriteRuntime(api, claims=SessionClaims()))
        self.assertEqual(result["code"], "current_payment_basis_unsupported")
        self.assertFalse(sends)

    def test_read_receipts_and_top_level_authorization_flags_are_rejected(self):
        state, _, _ = confirmed()
        bad = deepcopy(state); bad["operations"][0]["receipt"] = {"success": True}
        with self.assertRaisesRegex(InvalidState, "Read operations"): clone_state(bad)
        for flag in ("confirmed", "write_authorized", "delivery_verified", "condition_verified"):
            bad = deepcopy(state); bad[flag] = True
            with self.assertRaisesRegex(InvalidState, "Authorization flags"): clone_state(bad)

    def test_reconciliation_distinguishes_failed_sent_and_unknown_without_send(self):
        for status in ("failed", "sent", "unknown"):
            state, api, spec = confirmed(); runtime = FakeRuntime(api)
            runtime.status = 422 if status == "failed" else 200
            runtime.error = TimeoutError() if status == "unknown" else None
            _, updated = execute_operation(state, 1, spec, runtime)
            if status == "sent":
                op = writes(updated)[0]; updated = initial_state(updated["history"][:op["sent_index"]+1])
            count = len(runtime.sends)
            result, _ = reconcile_operation(updated, writes(updated)[0]["call_id"], runtime)
            self.assertEqual(result["code"], {"failed":"write_rejected", "sent":"write_sent_unresolved", "unknown":"write_result_unknown"}[status])
            self.assertEqual(len(runtime.sends), count)
