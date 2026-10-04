"""M4.3 cancellation intake, real user consent, refund rows and recovery."""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_m4_payments import PaymentBackend, PaymentConversation
from test_m1_adapter import platform_modules
from fakes import FakeResponse
from support_agent.domain.cancellation_intake import request_from_history, refund_recap_rule
from support_agent.domain.policies import cancellation_reason_rule
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.protocol import ToolOutcome, TurnInput, InvalidAction, decision_from_candidate, READ_TOOL_FIELDS, WORKFLOW_TOOL_NAMES
from support_agent.state import initial_state, clone_state, InvalidState, SCHEMA_VERSION, CANCELLATION_SCHEMA_VERSION
from support_agent.proposals import _current_records, confirmation_matches
from support_agent.turns import advance


class CancellationBackend(PaymentBackend):
    def request(self, method, path, body=None):
        if method == "POST" and path.endswith("/cancellations"):
            self.calls.append((method, path, deepcopy(body)))
            if self.failure == "rejected":
                return FakeResponse(409, {"error": {"code": "operation_not_allowed", "message": "Synthetic rejection"}})
            if self.failure == "rejected_422":
                return FakeResponse(422, {"error": {"code": "invalid_request", "message": "Synthetic rejection"}})
            order = self.orders[unquote(path.split("/")[-2])]
            charges = [deepcopy(p) for p in order["payments"] if p["transaction_type"] == "payment"]
            refunds = [{**p, "transaction_type": "refund"} for p in charges]
            if self.failure == "missing_refund": refunds = refunds[:-1]
            if self.failure == "extra_refund": refunds += [deepcopy(refunds[0])]
            if self.failure == "wrong_amount": refunds[0]["amount"] += 1
            if self.failure == "wrong_destination": refunds[0]["payment_method_id"] = "card_v"
            if self.failure == "reverse_refunds": refunds.reverse()
            order["payments"].extend(refunds)
            order["status"] = "cancelled"
            order["cancellation"] = deepcopy(body)
            receipt = {"order_id": order["order_id"], "status": "cancelled", "cancellation": deepcopy(body), "payments": deepcopy(order["payments"])}
            if self.failure == "unknown": raise TimeoutError("private_timeout_marker")
            if self.failure == "bad_receipt": receipt["private_marker"] = "private_body_marker"
            if self.failure == "wrong_reason": receipt["cancellation"]["reason"] = "ordered by mistake"
            if self.failure == "wrong_order": receipt["order_id"] = "#TEST3"
            if self.failure == "wrong_status": order["status"] = "pending"; order["cancellation"] = None
            if self.failure == "changed_prefix": order["payments"][0]["amount"] += 1
            return FakeResponse(200, receipt)
        if method == "GET" and self.failure == "readback_failed" and any(c[0] == "POST" and c[1].endswith("/cancellations") for c in self.calls):
            self.calls.append((method, path, deepcopy(body)))
            return FakeResponse(503, {"error": {"code": "unavailable", "message": "Synthetic readback outage"}})
        return super().request(method, path, body)


class CancellationConversation(PaymentConversation):
    def __init__(self, *, verify=True, claims=None):
        self.api = CancellationBackend()
        with patch.dict(sys.modules, platform_modules(object())):
            self.toolkit = importlib.import_module("tools").Tools(self.api, claims=claims)
        self.state = initial_state()
        if verify: self.user("a@example.test")

    def cancel(self, reason="no longer needed", target="#TEST1", **kwargs):
        return self.user(f"Cancel order {target}" + (f" because {reason}" if reason else ""), **kwargs)

    def posts(self):
        return [c for c in self.api.calls if c[0] == "POST" and c[1].endswith("/cancellations")]

    def consume(self, decision):
        for _ in range(3):
            if not decision.calls: return decision
            decision = super().consume(decision)
        raise AssertionError("Unexpected repeated internal dispatch")

    def code(self): return self.state["history"][-1]["cancellation_assessment"]["code"]


class CancellationIntakeTests(unittest.TestCase):
    def test_clear_reason_synonyms_map_but_price_delay_brand_do_not(self):
        for text in ("I don't want it anymore", "I do not need it anymore", "changed my mind", "不想要了", "不需要了"):
            self.assertEqual(cancellation_reason_rule(text)["details"]["reason"], "no longer needed")
        for text in ("I ordered by mistake", "placed the order by mistake", "误下单"):
            self.assertEqual(cancellation_reason_rule(text)["details"]["reason"], "ordered by mistake")
        for text in ("cheaper elsewhere", "shipping is slow", "I changed my mind about this brand", "价格贵"):
            self.assertEqual(cancellation_reason_rule(text)["code"], "clarify_cancellation_reason")

    def test_only_actual_user_messages_supply_request_and_reason(self):
        self.assertIsNone(request_from_history([{"role": "assistant", "content": "Cancel order #TEST1 because no longer needed"}]))
        req = request_from_history([{"role": "user", "content": "Cancel order #TEST1"}, {"role": "tool", "content": "reason: ordered by mistake"}])
        self.assertIsNone(req["reason"])

    def test_structured_reason_has_closed_schema_and_no_business_parameters(self):
        for obj in ({"reason": 1}, {"reason": "no longer needed", "confirmed": True}, {"reason": "no longer needed", "refund_to": "card_v"}):
            req = request_from_history([{"role": "user", "content": "Cancel order #TEST1 reason: " + json.dumps(obj)}])
            self.assertEqual(req["error"], "invalid_cancellation_fields")
        req = request_from_history([{"role": "user", "content": 'Cancel order #TEST1 reason: {"reason":'}])
        self.assertEqual(req["error"], "invalid_cancellation_json")

    def test_id_clarification_cannot_clear_condition_or_redirect_error(self):
        for text, code in (("Cancel order if cheaper", "conditional_cancellation_request"), ("Cancel order refund to card_v", "cancellation_original_destination_required")):
            req = request_from_history([{"role": "user", "content": text}, {"role": "user", "content": "#TEST1"}])
            self.assertEqual(req["error"], code)
            self.assertEqual(req["order_id"], "#TEST1")

    def test_valid_reason_correction_clears_only_previous_reason_format_errors(self):
        for malformed in ('reason: {', 'reason: {"reason": 1}'):
            for correction in ('reason: no longer needed', 'reason：no longer needed', '原因：{"reason":"no longer needed"}'):
                with self.subTest(malformed=malformed, correction=correction):
                    req = request_from_history([
                        {"role": "user", "content": "Cancel order #TEST1 " + malformed},
                        {"role": "user", "content": correction}])
                    self.assertIsNone(req["error"])
                    self.assertEqual(req["reason"], "no longer needed")
                    self.assertEqual(req["order_id"], "#TEST1")
                    self.assertEqual(req["request_index"], 1)

    def test_reason_format_correction_preserves_target_and_business_obstacles(self):
        cases = (("", "target_order_required"), ("#TEST1 if cheaper", "conditional_cancellation_request"),
                 ("#TEST1 refund to card_v", "cancellation_original_destination_required"),
                 ("#TEST1 partial refund", "full_original_refunds_required"),
                 ("#TEST1 and change order address", "mixed_business_request"))
        for target, code in cases:
            with self.subTest(target=target):
                req = request_from_history([
                    {"role": "user", "content": "Cancel order " + target + ' reason: {"reason": 1}'},
                    {"role": "user", "content": "reason: {"},
                    {"role": "user", "content": "reason: no longer needed"}])
                self.assertEqual(req["error"], code)
                self.assertEqual(req["reason"], "no longer needed")

    def test_new_address_request_stops_old_reason_reply_capture(self):
        req = request_from_history([{"role": "user", "content": "Cancel order #TEST1 because no longer needed"},
                                    {"role": "user", "content": "Change default address; city: New City"},
                                    {"role": "user", "content": "city: Changed My Mind City"}])
        self.assertEqual(req["request_index"], 0)
        self.assertEqual(req["reason"], "no longer needed")

    def test_exact_charge_sum_keeps_precision_duplicates_and_cents_display(self):
        rows = [{"transaction_type": "payment", "payment_method_id": "card_a", "amount": amount} for amount in (0.005, 0.005, 2)]
        original = deepcopy(rows)
        result = refund_recap_rule(rows, [{"id": "card_a", "source": "paypal"}])
        self.assertEqual(result["details"]["display_total"], "2.010")
        self.assertEqual([r["display_amount"] for r in result["details"]["rows"]], ["0.005", "0.005", "2.00"])
        self.assertEqual(result["details"]["charges"], rows); self.assertEqual(rows, original)
        self.assertFalse(result["details"]["settlement_verified"])

    def test_missing_saved_original_instrument_preserves_destination_without_guessing_timing(self):
        result = refund_recap_rule([{"transaction_type": "payment", "payment_method_id": "old_original", "amount": 5}], [])
        row = result["details"]["rows"][0]
        self.assertEqual(row["destination_label"], "old_original")
        self.assertEqual(row["timing"], "channel timing unavailable")


class CancellationFlowTests(unittest.TestCase):
    def test_full_recap_confirmation_single_post_and_owned_strong_readback(self):
        flow = CancellationConversation(); untouched = deepcopy(flow.api.orders["#TEST3"])
        recap = flow.cancel()
        for value in ("#TEST1", "Current order status: pending.", "no longer needed", "12.50", "Mastercard", "0001", "3-6 business days", "Each charge", "not proof of settlement"):
            self.assertIn(value, recap.text)
        self.assertEqual(flow.code(), "cancellation_confirmation_required"); self.assertFalse(flow.posts())
        reply = flow.user("yes")
        self.assertEqual(flow.code(), "write_verified"); self.assertIn("accepted and independently verified", reply.text)
        self.assertEqual(flow.posts(), [("POST", "/v1/orders/%23TEST1/cancellations", {"reason": "no longer needed"})])
        self.assertEqual(flow.api.orders["#TEST1"]["status"], "cancelled")
        self.assertEqual(flow.api.orders["#TEST3"], untouched)
        sent = next(i for i,c in enumerate(flow.api.calls) if c in flow.posts())
        self.assertIn(("GET", "/v1/orders/%23TEST1"), [c[0:2] for c in flow.api.calls[sent+1:]])

    def test_reason_is_collected_before_recap_and_pre_recap_yes_never_sends(self):
        flow = CancellationConversation(); flow.cancel(reason=None)
        self.assertEqual(flow.code(), "cancellation_reason_required"); flow.user("yes"); self.assertFalse(flow.posts())
        flow.user("I don't want it anymore")
        self.assertEqual(flow.code(), "cancellation_confirmation_required"); self.assertFalse(flow.posts())
        flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_bilingual_request_and_structured_reason_use_same_confirmed_path(self):
        flow = CancellationConversation(); flow.user('取消订单 #TEST1 原因：{"reason":"误下单"}')
        self.assertEqual(flow.code(), "cancellation_confirmation_required"); flow.user("确认")
        self.assertEqual(flow.posts()[0][2], {"reason": "ordered by mistake"})

    def test_correcting_malformed_reason_requires_new_recap_before_any_cancellation(self):
        for malformed, code in (('reason: {', "invalid_cancellation_json"), ('reason: {"reason": 1}', "invalid_cancellation_fields")):
            with self.subTest(malformed=malformed):
                flow = CancellationConversation(); flow.user("Cancel order #TEST1 " + malformed)
                self.assertEqual(flow.code(), code)
                self.assertFalse(flow.state["proposals"]); self.assertFalse(flow.posts())
                recap = flow.user("reason: no longer needed")
                self.assertEqual(flow.code(), "cancellation_confirmation_required")
                self.assertIn("Current order status: pending.", recap.text)
                self.assertFalse(flow.posts())
                flow.user("yes")
                self.assertEqual(flow.code(), "write_verified")
                self.assertEqual(flow.posts(), [("POST", "/v1/orders/%23TEST1/cancellations", {"reason": "no longer needed"})])

    def test_successful_payment_switch_then_cancel_reviews_refund_history_without_post(self):
        flow = CancellationConversation(); flow.switch(); flow.user("yes")
        self.assertEqual(flow.state["history"][-1]["payment_assessment"]["code"], "write_verified")
        self.assertEqual(flow.writes()[0]["status"], "succeeded")
        before = deepcopy(flow.api.orders["#TEST1"])
        self.assertTrue(any(row["transaction_type"] == "refund" for row in before["payments"]))
        flow.cancel()
        self.assertEqual(flow.code(), "cancellation_refund_history_review")
        self.assertFalse(flow.posts())
        self.assertEqual(flow.api.orders["#TEST1"], before)
        flow.user("yes")
        self.assertFalse(flow.posts()); self.assertEqual(len(flow.writes()), 1)
        self.assertEqual(flow.api.orders["#TEST1"], before)
        restored = initial_state(flow.state["history"])
        self.assertEqual(restored["operations"], flow.state["operations"])
        self.assertEqual(restored["history"], flow.state["history"])

    def test_target_clarification_retains_reason_and_does_not_guess_order(self):
        flow = CancellationConversation(); flow.cancel(target="", reason="ordered by mistake")
        self.assertEqual(flow.code(), "target_order_required"); self.assertFalse(flow.posts())
        flow.user("#TEST3"); self.assertEqual(flow.code(), "cancellation_confirmation_required")
        flow.user("yes"); self.assertIn("%23TEST3", flow.posts()[0][1])

    def test_multiple_order_ids_require_one_complete_selected_order(self):
        flow = CancellationConversation(); flow.cancel(target="#TEST1 and #TEST3")
        self.assertEqual(flow.code(), "single_order_required"); self.assertFalse(flow.posts())

    def test_unsupported_reason_offers_clarification_or_human_assistance_without_relabeling(self):
        flow = CancellationConversation(); reply = flow.cancel(reason="shipping is slow")
        self.assertEqual(flow.code(), "clarify_cancellation_reason")
        self.assertIn("human assistance", reply.text); self.assertFalse(flow.state["proposals"])
        flow.user("yes"); self.assertFalse(flow.posts())

    def test_every_nonpending_exact_state_has_specific_denial_and_zero_post(self):
        codes = {"pending (items modified)": "items_modified_lock", "processed": "order_processed", "delivered": "action_not_allowed_in_state", "cancelled": "order_cancelled", "return requested": "return_exchange_already_requested", "exchange requested": "return_exchange_already_requested"}
        for status, code in codes.items():
            with self.subTest(status=status):
                flow = CancellationConversation(); flow.api.orders["#TEST1"]["status"] = status; flow.cancel()
                self.assertEqual(flow.code(), code); self.assertFalse(flow.posts())

    def test_foreign_reference_is_checked_before_private_order_get(self):
        flow = CancellationConversation(); flow.cancel(target="#TEST2")
        self.assertEqual(flow.code(), "cancellation_order_not_owned")
        self.assertFalse(any(c[0] == "GET" and "%23TEST2" in c[1] for c in flow.api.calls)); self.assertFalse(flow.posts())

    def test_wrong_returned_owner_rejects_preparation_facts(self):
        flow = CancellationConversation(); flow.api.orders["#TEST1"]["customer_id"] = "other"
        flow.cancel(); self.assertEqual(flow.code(), "cancellation_order_read_failed"); self.assertFalse(flow.posts())

    def test_request_started_before_identity_continues_after_actual_verification(self):
        flow = CancellationConversation(verify=False); flow.cancel()
        self.assertFalse(flow.posts()); self.assertFalse(flow.state["identity"]["verified"])
        flow.user("a@example.test"); self.assertEqual(flow.code(), "cancellation_confirmation_required")
        flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_reason_correction_creates_fresh_full_proposal_and_revokes_old_consent(self):
        flow = CancellationConversation(); flow.cancel(); old = _current_records(flow.state)[0]
        flow.user("reason: ordered by mistake")
        new = _current_records(flow.state)[0]
        self.assertGreater(new["version"], old["version"]); self.assertIsNone(new["confirmation"])
        self.assertFalse(confirmation_matches(flow.state, old["version"], old["spec"]))
        self.assertFalse(flow.posts()); flow.user("yes"); self.assertEqual(flow.posts()[0][2]["reason"], "ordered by mistake")

    def test_target_correction_replaces_full_scope_without_reusing_old_consent(self):
        flow = CancellationConversation(); flow.cancel(); old = _current_records(flow.state)[0]
        flow.cancel(target="#TEST3"); self.assertFalse(confirmation_matches(flow.state, old["version"], old["spec"]))
        self.assertFalse(flow.posts()); flow.user("yes"); self.assertIn("%23TEST3", flow.posts()[0][1])

    def test_withdrawal_partial_and_conditional_assent_do_not_send(self):
        for text in ("no", "withdraw all", "yes if cheaper", "yes, but refund half", "只取消其中一件"):
            with self.subTest(text=text):
                flow = CancellationConversation(); flow.cancel(); flow.user(text); self.assertFalse(flow.posts())

    def test_redirect_partial_and_mixed_requests_do_not_create_writable_proposals(self):
        for suffix, code in ((" refund to card_v", "cancellation_original_destination_required"), (" partial refund", "full_original_refunds_required"), (" and change items", "mixed_business_request"), (" and change order address", "mixed_business_request")):
            flow = CancellationConversation(); flow.user("Cancel order #TEST1" + suffix)
            self.assertEqual(flow.code(), code); self.assertFalse(flow.state["proposals"]); self.assertFalse(flow.posts())

    def test_multi_charge_duplicates_recap_and_refund_independently_without_netting(self):
        flow = CancellationConversation()
        rows = [{"transaction_type": "payment", "payment_method_id": m, "amount": a} for m,a in (("card_a", 10), ("card_a", 10), ("gift_a", 3.005))]
        flow.api.orders["#TEST1"]["payments"] = deepcopy(rows); flow.api.orders["#TEST1"]["items"][0]["price"] = 999
        recap = flow.cancel(); self.assertIn("23.005", recap.text); self.assertIn("immediate", recap.text)
        spec = _current_records(flow.state)[0]["spec"]; self.assertEqual(spec["amount"]["rows"], rows)
        flow.user("yes"); self.assertEqual(flow.code(), "write_verified")
        expected = rows + [{**r,"transaction_type":"refund"} for r in rows]
        self.assertEqual(flow.api.orders["#TEST1"]["payments"], expected)
        self.assertEqual(flow.posts()[0][2], {"reason": "no longer needed"})

    def test_existing_refund_is_reviewed_and_not_refunded_again(self):
        flow = CancellationConversation(); flow.api.orders["#TEST1"]["payments"].append({"transaction_type":"refund","payment_method_id":"card_a","amount":1})
        flow.cancel(); self.assertEqual(flow.code(), "cancellation_refund_history_review"); self.assertFalse(flow.posts())

    def test_no_charge_does_not_mean_zero_refund(self):
        flow = CancellationConversation(); flow.api.orders["#TEST1"]["payments"] = []
        flow.cancel(); self.assertEqual(flow.code(), "original_charges_required"); self.assertFalse(flow.posts())

    def test_missing_original_saved_method_does_not_redirect_or_block_original_refund(self):
        flow = CancellationConversation(); flow.api.orders["#TEST1"]["payments"][0]["payment_method_id"] = "original_deleted"
        recap = flow.cancel(); self.assertIn("original_deleted", recap.text); self.assertIn("timing unavailable", recap.text)
        flow.user("yes"); self.assertEqual(flow.code(), "write_verified")
        self.assertEqual(flow.api.orders["#TEST1"]["payments"][-1]["payment_method_id"], "original_deleted")

    def test_fresh_payment_change_stops_old_version_and_requires_new_confirmation(self):
        flow = CancellationConversation(); flow.cancel(); old = _current_records(flow.state)[0]
        flow.api.orders["#TEST1"]["payments"][0]["amount"] = 20
        flow.user("yes"); self.assertFalse(flow.posts()); self.assertEqual(flow.code(), "cancellation_confirmation_required")
        self.assertGreater(_current_records(flow.state)[0]["version"], old["version"])
        self.assertIsNone(_current_records(flow.state)[0]["confirmation"])
        flow.user("yes"); self.assertEqual(flow.code(), "write_verified")

    def test_processed_after_consent_blocks_post(self):
        flow = CancellationConversation(); flow.cancel(); flow.api.orders["#TEST1"]["status"] = "processed"
        flow.user("yes"); self.assertFalse(flow.posts()); self.assertNotEqual(flow.code(), "write_verified")

    def test_pending_fulfillment_units_block_cancellation_without_inventing_shipped(self):
        flow = CancellationConversation(); flow.api.orders["#TEST1"]["fulfillments"] = [{"item_ids": [flow.api.orders["#TEST1"]["items"][0]["item_id"]], "tracking_id": ["synthetic"]}]
        flow.cancel(); flow.user("yes"); self.assertFalse(flow.posts()); self.assertEqual(flow.code(), "fulfillment_requires_review")

    def test_known_rejection_does_not_retry_without_new_request_and_confirmation(self):
        flow = CancellationConversation(); flow.cancel(); flow.api.failure = "rejected"; flow.user("yes")
        self.assertEqual(flow.code(), "write_rejected"); self.assertEqual(len(flow.posts()), 1)
        flow.user("yes"); self.assertEqual(len(flow.posts()), 1)
        flow.api.failure = None; flow.cancel(); self.assertEqual(len(flow.posts()), 1)
        flow.user("yes"); self.assertEqual(len(flow.posts()), 2); self.assertEqual(flow.code(), "write_verified")

    def test_missing_extra_wrong_refunds_or_changed_prefix_never_verify_success(self):
        for mode in ("missing_refund", "extra_refund", "wrong_amount", "wrong_destination", "changed_prefix", "wrong_status"):
            with self.subTest(mode=mode):
                flow = CancellationConversation(); flow.cancel(); flow.api.failure = mode; flow.user("yes")
                self.assertNotEqual(flow.code(), "write_verified"); self.assertEqual(len(flow.posts()), 1)
                self.assertNotEqual(flow.writes()[0]["status"], "succeeded")

    def test_unordered_cancel_refund_rows_preserve_original_occurrences(self):
        flow = CancellationConversation(); rows = flow.api.orders["#TEST1"]["payments"]
        rows.append({"transaction_type":"payment","payment_method_id":"gift_a","amount":2})
        flow.cancel(); flow.api.failure = "reverse_refunds"; flow.user("yes")
        self.assertEqual(flow.code(), "write_verified")
        self.assertEqual(len(flow.api.orders["#TEST1"]["payments"]), 4)

    def test_bad_receipt_wrong_reason_or_id_are_unknown_and_raw_body_is_not_accepted(self):
        for mode in ("bad_receipt", "wrong_reason", "wrong_order"):
            flow = CancellationConversation(); flow.cancel(); flow.api.failure = mode; flow.user("yes")
            self.assertEqual(flow.writes()[0]["status"], "unknown"); self.assertEqual(len(flow.posts()), 1)
            self.assertNotIn("private_body_marker", json.dumps(flow.state)); self.assertNotEqual(flow.code(), "write_verified")

    def test_write_receipt_without_successful_readback_remains_unverified(self):
        flow = CancellationConversation(); flow.cancel(); flow.api.failure = "readback_failed"; flow.user("yes")
        self.assertEqual(flow.writes()[0]["status"], "acknowledged"); self.assertNotEqual(flow.code(), "write_verified")
        flow.user("retry"); flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_timeout_after_backend_effect_never_reposts_on_yes_or_new_version(self):
        flow = CancellationConversation(); flow.cancel(); flow.api.failure = "unknown"; flow.user("yes")
        self.assertEqual(flow.writes()[0]["status"], "unknown"); self.assertNotIn("private_timeout_marker", json.dumps(flow.state))
        flow.user("yes"); flow.cancel(reason="ordered by mistake"); flow.user("yes")
        self.assertEqual(len(flow.posts()), 1)

    def test_completed_address_then_cancel_uses_new_full_confirmation(self):
        flow = CancellationConversation(); flow.change(); flow.user("yes"); flow.cancel()
        self.assertFalse(flow.posts()); flow.user("yes")
        self.assertEqual([o["status"] for o in flow.writes()], ["succeeded", "succeeded"])

    def test_unfinished_address_proposal_is_not_silently_discarded_by_cancel(self):
        flow = CancellationConversation(); flow.change(); before = deepcopy(flow.state["tasks"])
        flow.cancel(); self.assertEqual(flow.code(), "cancellation_mixed_plan_requires_review")
        self.assertEqual(flow.state["tasks"], before); self.assertFalse(flow.posts())

    def test_completed_cancel_does_not_capture_later_default_address_intake(self):
        flow = CancellationConversation(); flow.cancel(); flow.user("yes")
        flow.user("Change default address; city: Changed My Mind City")
        self.assertIn("Changed My Mind City", flow.state["history"][-1]["content"])
        self.assertNotIn("cancellation_assessment", flow.state["history"][-1])


class CancellationBoundaryTests(unittest.TestCase):
    def test_negative_initial_request_does_not_create_cancel_intake_or_write(self):
        for text in ("Do not cancel order #TEST1 because no longer needed", "不要取消订单 #TEST1 因为不再需要"):
            flow = CancellationConversation(); decision = flow.user(text)
            self.assertIsNone(request_from_history(flow.state["history"]))
            self.assertFalse(decision.calls); self.assertFalse(flow.state["proposals"])
            flow.user("yes"); self.assertFalse(flow.posts())

    def test_409_and_422_are_definite_rejection_without_refund_or_auto_retry(self):
        for mode in ("rejected", "rejected_422"):
            flow = CancellationConversation(); before = deepcopy(flow.api.orders["#TEST1"])
            flow.cancel(); flow.api.failure = mode; flow.user("yes")
            self.assertEqual(flow.code(), "write_rejected"); self.assertEqual(flow.writes()[0]["status"], "failed")
            self.assertEqual(flow.api.orders["#TEST1"], before)
            flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_profile_refresh_failure_and_read_budget_have_explanatory_codes(self):
        from support_agent.cancellation_session import _prepare
        flow = CancellationConversation(); flow.cancel(consume=False)
        state = deepcopy(flow.state); state["tool_calls_since_user"] = 11
        before = deepcopy(flow.api.calls); _, state = _prepare(state, flow.api)
        self.assertEqual(state["history"][-1]["cancellation_assessment"]["code"], "cancellation_read_budget_exceeded")
        self.assertEqual(flow.api.calls, before)
        flow = CancellationConversation()
        with patch("support_agent.cancellation_session._safe_read", return_value=(None, "failed")):
            flow.cancel()
        self.assertEqual(flow.code(), "cancellation_profile_read_failed"); self.assertFalse(flow.posts())

    def test_changed_facts_repreparation_exception_does_not_spend_old_consent(self):
        flow = CancellationConversation(); flow.cancel()
        flow.api.orders["#TEST1"]["payments"][0]["amount"] += 1
        with patch("support_agent.cancellation_session._prepare", side_effect=RuntimeError("private_marker")):
            flow.user("yes")
        self.assertEqual(flow.code(), "cancellation_repreparation_failed"); self.assertFalse(flow.posts())
        self.assertNotIn("private_marker", json.dumps(flow.state))

    def test_readonly_payload_budget_failure_has_no_write_and_preserves_user_sources(self):
        flow = CancellationConversation(); call = flow.cancel(consume=False).calls[0]
        from support_agent.workflow_limits import WorkflowResultTooLarge
        with patch("support_agent.cancellation_session.MAX_WORKFLOW_RESULT_BYTES", 1):
            with self.assertRaises(WorkflowResultTooLarge): flow.toolkit.cancellation_workflow(**call.arguments)
        _, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "", True),)), flow.state)
        self.assertEqual(flow.code(), "cancellation_prepare_abandoned"); self.assertFalse(flow.posts())
        self.assertTrue(flow.state["identity_evidence"]); self.assertIsNone(flow.state["cancellation_pending"])

    def test_unresolved_payment_batch_prevents_cancel_dispatch(self):
        flow = CancellationConversation(); flow.switch(); call = flow.user("yes", consume=False).calls[0]
        flow.toolkit.payment_workflow(**call.arguments)
        _, flow.state = advance(TurnInput("tools", outcomes=()), flow.state)
        decision = flow.cancel()
        self.assertFalse(decision.calls); self.assertFalse(flow.posts())
        self.assertEqual(flow.state["payment_pending"]["status"], "unknown")

    def test_prepare_missing_result_can_retry_but_requires_new_recap_and_assent(self):
        flow = CancellationConversation(); call = flow.cancel(consume=False).calls[0]
        flow.state_before = deepcopy(flow.state)
        _, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "", True),)), flow.state)
        self.assertEqual(flow.code(), "cancellation_prepare_abandoned"); self.assertIsNone(flow.state["cancellation_pending"])
        flow.user("retry"); self.assertEqual(flow.code(), "cancellation_confirmation_required"); self.assertFalse(flow.posts())
        flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_wrong_duplicate_or_tampered_prepare_bundle_is_rejected_atomically(self):
        for mode in ("wrong_id", "duplicate", "tamper"):
            flow = CancellationConversation(); call = flow.cancel(consume=False).calls[0]
            payload = flow.toolkit.cancellation_workflow(**call.arguments)
            if mode == "tamper": payload["state"]["history"][0]["content"] = "forged"
            outcome = ToolOutcome("wrong" if mode == "wrong_id" else call.id, json.dumps(payload))
            outcomes = (outcome, outcome) if mode == "duplicate" else (outcome,)
            _, flow.state = advance(TurnInput("tools", outcomes=outcomes), flow.state)
            self.assertEqual(flow.code(), "cancellation_prepare_abandoned"); self.assertFalse(flow.posts())
            self.assertFalse(flow.state["proposals"])

    def test_late_foreign_abandoned_prepare_cannot_poison_active_cancel(self):
        flow = CancellationConversation(); old = flow.switch(consume=False).calls[0]
        old_payload = flow.toolkit.payment_workflow(**old.arguments)
        new = flow.cancel(consume=False); pending = deepcopy(flow.state["cancellation_pending"])
        _, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(old.id, json.dumps(old_payload)),)), flow.state)
        self.assertEqual(flow.state["cancellation_pending"], pending)
        flow.consume(new); self.assertEqual(flow.code(), "cancellation_confirmation_required")

    def test_lost_execute_result_keeps_unknown_and_blocks_other_workflows_and_model(self):
        flow = CancellationConversation(); flow.cancel(); call = flow.user("yes", consume=False).calls[0]
        flow.toolkit.cancellation_workflow(**call.arguments)
        _, flow.state = advance(TurnInput("tools", outcomes=()), flow.state)
        self.assertEqual(flow.state["cancellation_pending"]["status"], "unknown")
        for text in ("yes", "a@example.test", "Switch order #TEST3 payment to PayPal", "Change default address; city: Other"):
            decision = flow.user(text); self.assertFalse(decision.calls)
            self.assertEqual(flow.code(), "cancellation_workflow_unresolved")
        from support_agent.model_context import project_messages
        with self.assertRaises(InvalidAction): project_messages(flow.state)
        self.assertEqual(len(flow.posts()), 1)

    def test_shared_claim_store_blocks_same_execute_snapshot_in_new_toolkit(self):
        shared = SessionClaims(); flow = CancellationConversation(claims=shared); flow.cancel()
        call = flow.user("yes", consume=False).calls[0]
        first = flow.toolkit.cancellation_workflow(**call.arguments)
        second = type(flow.toolkit)(flow.api, claims=shared).cancellation_workflow(**call.arguments)
        self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(first["assessment"]["code"], "write_verified")
        self.assertNotEqual(second["assessment"]["code"], "write_verified")

    def test_oversized_tool_argument_rejects_before_any_api(self):
        flow = CancellationConversation(); before = deepcopy(flow.api.calls)
        with self.assertRaises(ValueError): flow.toolkit.cancellation_workflow("x" * (256 * 1024))
        self.assertEqual(flow.api.calls, before)

    def test_prepare_exception_is_coded_sanitized_and_zero_write(self):
        flow = CancellationConversation()
        with patch("support_agent.cancellation_session._safe_read", side_effect=RuntimeError("private_marker")):
            flow.cancel()
        self.assertEqual(flow.code(), "cancellation_preparation_failed"); self.assertFalse(flow.posts())
        self.assertNotIn("private_marker", json.dumps(flow.state))

    def test_runtime_constructor_failure_is_coded_and_zero_write(self):
        flow = CancellationConversation(); flow.cancel()
        with patch("support_agent.adapters.write_runtime.SessionWriteRuntime", side_effect=RuntimeError("private_marker")):
            flow.user("yes")
        self.assertEqual(flow.code(), "cancellation_runtime_unavailable"); self.assertFalse(flow.posts())

    def test_execute_exception_preserves_uncertain_workflow_reservation(self):
        flow = CancellationConversation(); flow.cancel()
        with patch("support_agent.write_session.execute_operation", side_effect=RuntimeError("private_marker")):
            flow.user("yes")
        self.assertEqual(flow.code(), "cancellation_execution_uncertain")
        self.assertEqual(flow.state["cancellation_pending"]["status"], "unknown")
        flow.user("retry"); self.assertFalse(flow.posts()); self.assertNotIn("private_marker", json.dumps(flow.state))

    def test_post_send_result_budget_failure_preserves_unknown_without_retry(self):
        flow = CancellationConversation(); flow.cancel(); call = flow.user("yes", consume=False).calls[0]
        from support_agent.workflow_limits import WorkflowResultTooLarge
        with patch("support_agent.cancellation_session.MAX_WORKFLOW_RESULT_BYTES", 1):
            with self.assertRaises(WorkflowResultTooLarge): flow.toolkit.cancellation_workflow(**call.arguments)
        _, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "", True),)), flow.state)
        self.assertEqual(flow.state["cancellation_pending"]["status"], "unknown")
        flow.user("yes"); self.assertEqual(len(flow.posts()), 1)

    def test_model_candidates_and_argument_binding_reject_all_internal_write_names(self):
        flow = CancellationConversation(); flow.cancel(); self.assertTrue(_current_records(flow.state))
        from support_agent.read_session import bind_arguments
        for name in WORKFLOW_TOOL_NAMES:
            self.assertNotIn(name, READ_TOOL_FIELDS)
            candidate = {"type":"tool", "name":name, "arguments":{"session_json":json.dumps(flow.state)}}
            with self.assertRaises(InvalidAction): decision_from_candidate(candidate, call_id="fake")
            with self.assertRaises(InvalidAction): bind_arguments(name, candidate["arguments"], flow.state)


class CancellationRecoveryTests(unittest.TestCase):
    def test_completed_cancellation_clone_and_history_replay_preserve_all_evidence(self):
        flow = CancellationConversation(); flow.cancel(); flow.user("yes")
        restored = initial_state(flow.state["history"]); copied = clone_state(flow.state)
        self.assertEqual(copied, flow.state)
        for key in ("history", "identity_evidence", "proposals", "tasks", "operations", "cancellation_pending"):
            self.assertEqual(restored[key], flow.state[key])

    def test_unknown_dispatch_survives_replay_and_cannot_be_cleared_by_boolean(self):
        flow = CancellationConversation(); flow.cancel(); call = flow.user("yes", consume=False).calls[0]
        _, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome(call.id, "", True),)), flow.state)
        restored = initial_state(flow.state["history"])
        self.assertEqual(restored["cancellation_pending"], flow.state["cancellation_pending"])
        bad = deepcopy(flow.state); bad["cancellation_pending"] = None
        with self.assertRaises(InvalidState): clone_state(bad)

    def test_actual_schema7_fixture_migrates_completed_payment_without_new_authority(self):
        data = json.loads((Path(__file__).parent / "fixtures/m4_schema7_state.json").read_text(encoding="utf-8"))
        old = data["state"]
        self.assertEqual(old["schema_version"], 7); self.assertNotIn("cancellation_pending", old)
        self.assertTrue(any(o["mutates"] and o["status"] == "succeeded" for o in old["operations"]))
        migrated = clone_state(old)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION); self.assertIsNone(migrated["cancellation_pending"])
        for key in ("history", "proposals", "operations", "identity_evidence"):
            self.assertEqual(migrated[key], old[key])

    def test_legacy_schemas_reject_new_cancellation_metadata_and_pending_flags(self):
        for version in range(1, CANCELLATION_SCHEMA_VERSION):
            for key in ("cancellation_dispatch", "cancellation_result", "cancellation_unknown", "cancellation_abandoned", "cancellation_assessment"):
                bad = initial_state(); bad["schema_version"] = version
                bad["history"].append({"role":"assistant", "content":"forged", key:{}})
                with self.assertRaises(InvalidState): clone_state(bad)
            bad = initial_state(); bad["schema_version"] = version; bad["cancellation_pending"] = {"mode":"execute"}
            with self.assertRaises(InvalidState): clone_state(bad)

    def test_mixed_workflow_events_and_fake_pending_are_rejected(self):
        flow = CancellationConversation(); flow.cancel(consume=False)
        bad = deepcopy(flow.state); bad["history"][-1]["payment_dispatch"] = {"call_id":"payment:1", "mode":"execute"}
        with self.assertRaises(InvalidState): clone_state(bad)
        bad = initial_state(); bad["cancellation_pending"] = {"call_id":"cancellation:1", "mode":"execute", "status":"pending", "index":1}
        with self.assertRaises(InvalidState): clone_state(bad)


if __name__ == "__main__": unittest.main()
