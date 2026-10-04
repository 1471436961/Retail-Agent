"""M4.2 actual-user/tool/recap/consent/payment/readback offline flows."""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_m4_addresses import AddressBackend, Conversation, NEW
from test_m1_adapter import platform_modules
from fakes import FakeResponse
from support_agent.domain.payment_intake import request_from_history, resolve_choice, current_charge_rule
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.payment_session import _boundary
from support_agent.protocol import ToolOutcome, TurnInput, InvalidAction, decision_from_candidate
from support_agent.state import initial_state, clone_state, InvalidState, SCHEMA_VERSION
from support_agent.proposals import _current_records, confirmation_matches
from support_agent.turns import advance


class PaymentBackend(AddressBackend):
    def __init__(self):
        super().__init__()
        self.customers["customer_a"]["payment_methods"] = [
            {"id":"card_a","source":"credit_card","brand":"Mastercard","last_four":"0001"},
            {"id":"card_v","source":"credit_card","brand":"Visa","last_four":"0002"},
            {"id":"paypal_a","source":"paypal"},
            {"id":"gift_a","source":"gift_card","balance":40.0}]
        for order_id in ("#TEST1","#TEST3"):
            self.orders[order_id]["payments"] = [{"transaction_type":"payment","payment_method_id":"card_a","amount":12.5}]
        self.legs = []

    def request(self, method, path, body=None):
        if method == "PUT" and path.endswith("/payment-method"):
            self.calls.append((method,path,deepcopy(body)))
            if self.failure == "rejected":
                return FakeResponse(402,{"error":{"code":"payment_failed","message":"Synthetic decline"}})
            order = self.orders[unquote(path.split("/")[-2])]
            if len(order["payments"]) != 1:
                return FakeResponse(409,{"error":{"code":"operation_not_allowed","message":"Synthetic historical rows"}})
            original = deepcopy(order["payments"][0]); selected=body["payment_method_id"]
            amount=original["amount"]
            methods={m["id"]:m for m in self.customers["customer_a"]["payment_methods"]}
            self.legs.append(("charge",selected,amount))
            if methods[selected]["source"] == "gift_card": methods[selected]["balance"] = round(methods[selected]["balance"]-amount,2)
            new={"transaction_type":"payment","payment_method_id":selected,"amount":amount}
            refund={**original,"transaction_type":"refund"}
            order["payments"].append(new)
            if self.failure != "missing_refund":
                order["payments"].append(refund); self.legs.append(("refund",original["payment_method_id"],amount))
                if methods[original["payment_method_id"]]["source"] == "gift_card": methods[original["payment_method_id"]]["balance"] = round(methods[original["payment_method_id"]]["balance"]+amount,2)
            if self.failure == "reversed_rows":
                # Change only representation, not this fake's processing order.
                order["payments"][1:] = [refund, new]
            receipt={"order_id":order["order_id"],"payments":deepcopy(order["payments"])}
            if self.failure == "receipt_order_mismatch":
                receipt["payments"][1:] = [refund, new]
            if self.failure == "unknown": raise TimeoutError("private_timeout_marker")
            if self.failure == "bad_receipt": receipt["private_marker"]="private_body_marker"
            if self.failure == "wrong_amount": order["payments"][-1]["amount"] += 1
            if self.failure == "wrong_destination": order["payments"][-1]["payment_method_id"]="card_v"
            if self.failure == "wrong_status": order["status"]="processed"
            return FakeResponse(200,receipt)
        return super().request(method,path,body)


class PaymentConversation(Conversation):
    def __init__(self, *, verify=True, claims=None):
        self.api=PaymentBackend()
        with patch.dict(sys.modules,platform_modules(object())):
            self.toolkit=importlib.import_module("tools").Tools(self.api,claims=claims)
        self.state=initial_state()
        if verify: self.user("a@example.test")

    def consume(self, decision):
        call=decision.calls[0]
        payload=getattr(self.toolkit,call.name)(**call.arguments)
        decision,self.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,json.dumps(payload)),)),self.state)
        return decision

    def switch(self, query="PayPal", target="#TEST1", **kwargs):
        return self.user(f"Switch order {target} payment to {query}",**kwargs)

    def code(self): return self.state["history"][-1]["payment_assessment"]["code"]

    def writes(self): return [o for o in self.state["operations"] if o["mutates"]]


class PaymentFlowTests(unittest.TestCase):
    def test_old_payment_draft_does_not_capture_address_fields_or_address_retry(self):
        flow=PaymentConversation(); flow.switch(); flow.user("yes")
        flow.user("Change default address; city: Visa City")
        self.assertIn("Visa City",flow.state["history"][-1]["content"])
        flow.user("city: Mastercard City")
        self.assertIn("Mastercard City",flow.state["history"][-1]["content"])
        call=flow.user("retry",consume=False).calls[0]
        self.assertEqual(call.name,"address_workflow")
    def test_completed_payment_and_later_address_share_one_identity_and_claim_store(self):
        flow=PaymentConversation(); flow.switch(); flow.user("yes")
        identity=deepcopy(flow.state["identity_evidence"])
        flow.change("default"); self.assertEqual(len(flow.puts()),1)
        flow.user("yes")
        self.assertEqual([o["name"] for o in flow.writes()],["payment_method","default_shipping_address"])
        self.assertEqual([o["status"] for o in flow.writes()],["succeeded","succeeded"])
        self.assertEqual(flow.state["identity_evidence"],identity)

    def test_completed_address_then_payment_has_fresh_separate_confirmation(self):
        flow=PaymentConversation(); flow.change(); flow.user("yes")
        flow.switch(); self.assertEqual(len(flow.puts()),1)
        self.assertEqual(flow.code(),"payment_confirmation_required")
        flow.user("yes"); self.assertEqual([o["status"] for o in flow.writes()],["succeeded","succeeded"])
    def test_bilingual_payment_request_and_explicit_saved_id_use_same_confirmed_path(self):
        flow=PaymentConversation(); flow.user('更换订单 #TEST1 支付方式，改用 PayPal')
        self.assertEqual(flow.code(),"payment_confirmation_required"); flow.user("确认")
        self.assertEqual(flow.puts()[0][2],{"payment_method_id":"paypal_a"})

    def test_saved_ids_are_opaque_even_when_their_text_contains_source_names(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"][2]["id"]="visa_paypal"
        flow.user('Change order #TEST1 payment: {"payment_method_id":"visa_paypal"}')
        self.assertEqual(flow.code(),"payment_confirmation_required"); flow.user("yes")
        self.assertEqual(flow.puts()[0][2],{"payment_method_id":"visa_paypal"})
    def test_paypal_recap_charge_refund_pending_and_independent_readback(self):
        flow=PaymentConversation(); before=deepcopy(flow.api.orders["#TEST3"])
        recap=flow.switch()
        for value in ("#TEST1","12.5","Mastercard","0001","paypal_a","3-6 business days",
                      "Payment-switch policy requires", "to succeed before", "submit one payment-method change",
                      "transaction-list order does not establish actual processing order"):
            self.assertIn(value,recap.text)
        self.assertNotIn("The backend charges", recap.text)
        self.assertFalse(flow.puts()); self.assertEqual(flow.code(),"payment_confirmation_required")
        reply=flow.user("yes")
        self.assertIn("accepted and independently verified",reply.text)
        self.assertNotIn("has arrived",reply.text)
        self.assertIn("do not independently prove processing order, settlement or arrival", reply.text)
        self.assertEqual(flow.puts(),[("PUT","/v1/orders/%23TEST1/payment-method",{"payment_method_id":"paypal_a"})])
        self.assertEqual(flow.api.legs,[("charge","paypal_a",12.5),("refund","card_a",12.5)])
        self.assertEqual(flow.api.orders["#TEST1"]["status"],"pending")
        self.assertEqual(flow.api.orders["#TEST3"],before)
        self.assertEqual(flow.writes()[0]["status"],"succeeded")
        self.assertEqual(flow.api.calls[-1][:2],("GET","/v1/orders/%23TEST1"))

    def test_exact_gift_balance_covers_whole_charge_and_only_one_method(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"][-1]["balance"]=12.5
        flow.switch("gift card"); flow.user("确认")
        self.assertEqual(flow.puts()[0][2],{"payment_method_id":"gift_a"})
        self.assertEqual(flow.api.customers["customer_a"]["payment_methods"][-1]["balance"],0)

    def test_insufficient_gift_card_has_zero_writes_and_keeps_original_payment(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"][-1]["balance"]=12.49
        original=deepcopy(flow.api.orders["#TEST1"])
        flow.switch("gift card"); flow.user("yes")
        self.assertFalse(flow.puts()); self.assertEqual(flow.api.orders["#TEST1"],original)
        self.assertTrue(any(e.get("payment_assessment",{}).get("code")=="insufficient_gift_card" for e in flow.state["history"]))

    def test_customer_specified_gift_insufficiency_fallback_recap_then_confirmation(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"][-1]["balance"]=1
        recap=flow.switch("gift card if sufficient otherwise Visa")
        self.assertIn("specified fallback",recap.text); self.assertIn("card_v",recap.text)
        self.assertFalse(flow.puts()); flow.user("yes")
        self.assertEqual(flow.puts()[0][2],{"payment_method_id":"card_v"})

    def test_sufficient_gift_card_does_not_take_customer_fallback(self):
        flow=PaymentConversation(); flow.switch("gift card if sufficient otherwise Visa")
        self.assertEqual(_current_records(flow.state)[0]["spec"]["parameters"],{"payment_method_id":"gift_a"})
        self.assertFalse(flow.puts())

    def test_no_fallback_is_invented_for_an_insufficient_gift_card(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"][-1]["balance"]=1
        reply=flow.switch("gift card")
        self.assertEqual(flow.code(),"insufficient_gift_card")
        self.assertIn("Saved methods",reply.text); self.assertFalse(_current_records(flow.state)); self.assertFalse(flow.puts())

    def test_original_gift_card_refund_timing_is_not_taken_from_new_paypal(self):
        flow=PaymentConversation(); flow.api.orders["#TEST1"]["payments"][0]["payment_method_id"]="gift_a"
        recap=flow.switch("PayPal")
        self.assertIn("Refund channel policy: immediate",recap.text)
        reply=flow.user("yes")
        self.assertIn("policy: immediate",reply.text); self.assertIn("not independently prove processing order, settlement",reply.text)
        self.assertEqual(flow.api.customers["customer_a"]["payment_methods"][-1]["balance"],52.5)

    def test_no_choice_lists_real_saved_methods_and_later_user_selects_one(self):
        flow=PaymentConversation(); flow.user("Change order #TEST1 payment")
        self.assertEqual(flow.code(),"payment_method_required")
        self.assertIn("card_v",flow.state["history"][-1]["content"])
        flow.user("Use Visa"); self.assertEqual(flow.code(),"payment_confirmation_required")
        flow.user("yes"); self.assertEqual(flow.puts()[0][2],{"payment_method_id":"card_v"})

    def test_ambiguous_brand_requires_last_four_or_exact_saved_id(self):
        flow=PaymentConversation(); flow.api.customers["customer_a"]["payment_methods"].append({"id":"visa_other","source":"credit_card","brand":"Visa","last_four":"7777"})
        flow.switch("Visa"); self.assertEqual(flow.code(),"payment_selection_ambiguous")
        flow.user("Use Visa ending 7777"); self.assertEqual(flow.code(),"payment_confirmation_required")
        flow.user("yes"); self.assertEqual(flow.puts()[0][2],{"payment_method_id":"visa_other"})

    def test_same_method_and_split_instruments_are_refused_before_put(self):
        for query, code in (("Mastercard","same_payment_method"),("Visa and PayPal","single_method_required"),("split across two cards","single_method_required")):
            with self.subTest(query=query):
                flow=PaymentConversation(); flow.switch(query)
                self.assertEqual(flow.code(),code); flow.user("yes"); self.assertFalse(flow.puts())

    def test_unknown_explicit_id_cannot_be_added_or_fall_back_silently(self):
        flow=PaymentConversation(); flow.user('Change order #TEST1 payment: {"payment_method_id":"new_card"}')
        self.assertEqual(flow.code(),"payment_method_not_saved"); self.assertFalse(flow.puts())

    def test_malformed_or_extra_payment_fields_are_not_confirmation(self):
        for body in ('{"payment_method_id":3}','{"payment_method_id":["card_v"]}','{"payment_method_id":"card_v","confirmed":true}','{broken}'):
            flow=PaymentConversation(); flow.user("Change order #TEST1 payment: "+body); flow.user("yes")
            self.assertFalse(flow.puts()); self.assertFalse(_current_records(flow.state))

    def test_payment_before_identity_continues_only_after_actual_verification(self):
        flow=PaymentConversation(verify=False); flow.switch()
        self.assertFalse(flow.api.calls)
        recap=flow.user("a@example.test")
        self.assertEqual(recap.calls[0].name,"payment_workflow")
        recap=flow.consume(recap)
        self.assertIn("Full order charge",recap.text); self.assertFalse(flow.puts())
        flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_order_ownership_precedes_get_and_private_saved_method_choices(self):
        flow=PaymentConversation(); flow.switch(target="#TEST2")
        self.assertEqual(flow.code(),"payment_order_not_owned")
        self.assertFalse(any(c[1]=="/v1/orders/%23TEST2" for c in flow.api.calls)); self.assertFalse(flow.puts())

    def test_missing_or_multiple_order_targets_are_clarified_not_guessed(self):
        for text, code in (("Change payment to Visa","target_order_required"),("Switch order #TEST1 and #TEST3 payment to Visa","single_order_required")):
            flow=PaymentConversation(); flow.user(text); self.assertEqual(flow.code(),code); self.assertFalse(flow.puts())

    def test_order_id_clarification_preserves_the_original_user_choice(self):
        flow=PaymentConversation(); flow.user("Change payment to PayPal"); flow.user("#TEST1")
        self.assertEqual(flow.code(),"payment_confirmation_required"); flow.user("yes"); self.assertEqual(flow.puts()[0][2],{"payment_method_id":"paypal_a"})

    def test_every_nonpending_exact_state_blocks_payment_switch(self):
        from support_agent.domain.orders import ORDER_STATUSES
        expected = {"pending (items modified)":"items_modified_lock", "processed":"order_processed",
                    "delivered":"action_not_allowed_in_state", "cancelled":"order_cancelled",
                    "exchange requested":"return_exchange_already_requested",
                    "return requested":"return_exchange_already_requested"}
        self.assertEqual(set(expected), ORDER_STATUSES-{"pending"})
        for status in ORDER_STATUSES-{"pending"}:
            with self.subTest(status=status):
                flow=PaymentConversation(); flow.api.orders["#TEST1"]["status"]=status
                flow.switch(); self.assertEqual(flow.code(), expected[status])
                assessment=flow.state["history"][-1]["payment_assessment"]
                self.assertEqual(assessment["decision"], "deny")
                self.assertEqual(assessment["details"]["records"][0]["code"], expected[status])
                flow.user("yes"); self.assertFalse(flow.puts())

    def test_history_refunds_multiple_charges_and_empty_history_are_not_netted(self):
        for records in ([],[{"transaction_type":"refund","payment_method_id":"card_a","amount":12.5}],
                        [{"transaction_type":"payment","payment_method_id":"card_a","amount":10},{"transaction_type":"payment","payment_method_id":"card_a","amount":2.5}]):
            flow=PaymentConversation(); flow.api.orders["#TEST1"]["payments"]=records
            flow.switch(); self.assertEqual(flow.code(),"current_payment_basis_unsupported"); self.assertFalse(flow.puts())

    def test_whole_charge_comes_from_payment_not_catalog_or_user_amount(self):
        flow=PaymentConversation(); flow.api.orders["#TEST1"]["items"][0]["price"]=999
        flow.switch(); spec=_current_records(flow.state)[0]["spec"]
        self.assertEqual(spec["amount"]["value"],12.5)
        self.assertEqual(spec["amount"]["refund_rows"],flow.api.orders["#TEST1"]["payments"])

    def test_zero_original_charge_is_supported_without_coercion_or_guessed_amount(self):
        flow=PaymentConversation(); flow.api.orders["#TEST1"]["payments"][0]["amount"]=0
        flow.switch(); flow.user("yes")
        self.assertEqual(flow.api.legs,[("charge","paypal_a",0),("refund","card_a",0)])

    def test_change_choice_requires_a_new_full_recap_and_invalidates_old_consent(self):
        flow=PaymentConversation(); flow.switch(); original=deepcopy(_current_records(flow.state)[0])
        flow.user("No, use Visa"); new=_current_records(flow.state)[0]
        self.assertGreater(new["version"],original["version"]); self.assertIsNone(new["confirmation"])
        self.assertFalse(confirmation_matches(flow.state,original["version"],original["spec"]))
        self.assertFalse(flow.puts()); flow.user("yes"); self.assertEqual(flow.puts()[0][2],{"payment_method_id":"card_v"})

    def test_pre_recap_yes_conditions_withdrawal_and_unrelated_text_never_send(self):
        for text in ("yes if cheaper","withdraw all","Thanks, tell me about mugs"):
            flow=PaymentConversation(); flow.user("yes"); flow.switch(); flow.user(text)
            self.assertFalse(flow.puts())

    def test_balance_amount_method_or_state_change_stops_old_version(self):
        for mutation in ("balance","amount","method","state"):
            flow=PaymentConversation(); flow.switch("gift card")
            if mutation=="balance": flow.api.customers["customer_a"]["payment_methods"][-1]["balance"]=1
            if mutation=="amount": flow.api.orders["#TEST1"]["payments"][0]["amount"]=15
            if mutation=="method": flow.api.customers["customer_a"]["payment_methods"].pop()
            if mutation=="state": flow.api.orders["#TEST1"]["status"]="processed"
            flow.user("yes"); self.assertFalse(flow.puts())
            self.assertNotEqual(flow.code(),"write_verified")

    def test_rejected_charge_keeps_order_and_has_no_refund_or_auto_retry(self):
        flow=PaymentConversation(); flow.switch(); original=deepcopy(flow.api.orders["#TEST1"])
        flow.api.failure="rejected"; flow.user("yes")
        self.assertEqual(flow.code(),"write_rejected"); self.assertEqual(flow.api.orders["#TEST1"],original)
        self.assertFalse(flow.api.legs); flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_after_decline_another_saved_method_requires_new_confirmation(self):
        flow=PaymentConversation(); flow.switch(); flow.api.failure="rejected"; flow.user("yes")
        flow.api.failure=None; flow.user("Use Visa")
        self.assertEqual(flow.code(),"payment_confirmation_required"); self.assertEqual(len(flow.puts()),1)
        flow.user("yes"); self.assertEqual(len(flow.puts()),2); self.assertEqual(flow.writes()[-1]["status"],"succeeded")

    def test_unknown_and_bad_receipt_never_retry_even_when_backend_is_changed(self):
        for failure in ("unknown","bad_receipt"):
            flow=PaymentConversation(); flow.switch(); flow.api.failure=failure; flow.user("yes")
            self.assertEqual(flow.writes()[0]["status"],"unknown")
            flow.user("Use Visa"); flow.user("yes")
            self.assertEqual(len(flow.puts()),1); self.assertNotIn("private_body_marker",json.dumps(flow.state))

    def test_missing_wrong_refund_or_post_switch_state_prevents_verified_success(self):
        for failure in ("missing_refund","wrong_amount","wrong_destination","wrong_status"):
            flow=PaymentConversation(); flow.switch(); flow.api.failure=failure
            reply=flow.user("yes"); self.assertNotIn("accepted and independently verified",reply.text)
            self.assertNotEqual(flow.writes()[0]["status"],"succeeded")
            flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_pending_fulfillment_stops_payment_write_at_shared_live_gate(self):
        flow=PaymentConversation(); flow.api.orders["#TEST1"]["fulfillments"]=[{"item_ids":["item_blue"],"tracking_id":["synthetic-tracking"]}]
        flow.switch(); flow.user("yes")
        self.assertEqual(flow.code(),"fulfillment_requires_review"); self.assertFalse(flow.puts())

    def test_opaque_payment_tool_cannot_be_a_model_candidate_or_read_bound_action(self):
        from support_agent.read_session import bind_arguments
        for name in ("payment_workflow","address_workflow"):
            with self.assertRaises(InvalidAction): decision_from_candidate({"type":"tool","name":name,"arguments":{"session_json":"{}"}},call_id="synthetic-model")
            with self.assertRaises(InvalidAction): bind_arguments(name,{"session_json":"{}"},PaymentConversation().state)

    def test_failed_profile_or_owned_order_read_does_not_reuse_old_facts(self):
        for target, expected_code in (("/v1/customers/customer_a","payment_profile_read_failed"),
                                      ("/v1/orders/%23TEST1","payment_order_read_failed")):
            flow=PaymentConversation(); original=flow.api.request
            def failed(method,path,body=None): return FakeResponse(503,{"error":{"code":"unavailable","message":"private_failure"}}) if path==target else original(method,path,body)
            with patch.object(flow.api,"request",side_effect=failed): flow.switch()
            self.assertEqual(flow.code(),expected_code); self.assertFalse(flow.puts())
            self.assertNotIn("private_failure",json.dumps(flow.state))

    def test_read_budget_requires_both_profile_and_order_before_starting(self):
        flow=PaymentConversation(); call=flow.switch(consume=False).calls[0]
        snapshot=json.loads(call.arguments["session_json"]); snapshot["tool_calls_since_user"]=11
        before=deepcopy(flow.api.calls); payload=flow.toolkit.payment_workflow(json.dumps(snapshot))
        self.assertEqual(payload["assessment"]["code"],"payment_read_budget_exceeded"); self.assertEqual(flow.api.calls,before)

    def test_unfinished_address_proposal_is_not_silently_replaced(self):
        flow=PaymentConversation(); flow.change(); before=deepcopy(flow.state["proposals"])
        flow.switch(); self.assertEqual(flow.code(),"payment_mixed_plan_requires_review")
        self.assertEqual([p["spec"] for p in flow.state["proposals"]],[p["spec"] for p in before]); self.assertFalse(flow.puts())


class PaymentRecoveryTests(unittest.TestCase):
    def test_missing_wrong_and_duplicate_prepare_outcomes_are_recoverable(self):
        for mode in ("missing","wrong","duplicate"):
            flow=PaymentConversation(); call=flow.switch(consume=False).calls[0]
            payload=json.dumps(flow.toolkit.payment_workflow(**call.arguments))
            outcomes=() if mode=="missing" else (ToolOutcome("wrong",payload),) if mode=="wrong" else (ToolOutcome(call.id,payload),ToolOutcome(call.id,payload))
            _,flow.state=advance(TurnInput("tools",outcomes=outcomes),flow.state)
            self.assertEqual(flow.code(),"payment_prepare_abandoned"); flow.user("retry")
            self.assertEqual(flow.code(),"payment_confirmation_required"); self.assertFalse(flow.puts())

    def test_runtime_setup_and_post_send_payload_overflow_preserve_safe_outcomes(self):
        from support_agent.workflow_limits import json_bytes, WorkflowResultTooLarge
        flow=PaymentConversation(); flow.switch(); flow.api.context.conversation_id=None
        calls=deepcopy(flow.api.calls); flow.user("yes")
        self.assertEqual(flow.code(),"payment_runtime_unavailable"); self.assertEqual(flow.api.calls,calls)
        flow=PaymentConversation(); flow.switch(); call=flow.user("yes",consume=False).calls[0]
        with patch("support_agent.payment_session.MAX_WORKFLOW_RESULT_BYTES",json_bytes(flow.state)+100):
            with self.assertRaises(WorkflowResultTooLarge): flow.toolkit.payment_workflow(**call.arguments)
        _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,"",True),)),flow.state)
        self.assertEqual(flow.state["payment_pending"]["status"],"unknown"); flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_repeated_success_reply_is_not_a_new_payment_authorization(self):
        flow=PaymentConversation(); flow.switch(); flow.user("yes"); flow.user("yes")
        self.assertEqual(len(flow.puts()),1)
    def test_successful_payment_restores_same_identity_consent_task_and_journal(self):
        flow=PaymentConversation(); flow.switch(); flow.user("yes")
        restored=initial_state(flow.state["history"])
        for key in ("history","identity_evidence","proposals","tasks","operations","payment_pending","address_pending"):
            self.assertEqual(restored[key],flow.state[key])
        self.assertEqual(clone_state(flow.state),flow.state)

    def test_real_schema6_fixture_migrates_without_new_payment_authority(self):
        fixture=json.loads((Path(__file__).parent/"fixtures/m4_schema6_state.json").read_text(encoding="utf-8"))
        old=fixture["state"]; before=deepcopy(old)
        self.assertEqual(old["schema_version"],6); self.assertNotIn("payment_pending",old)
        migrated=clone_state(old)
        self.assertEqual(migrated["schema_version"],SCHEMA_VERSION); self.assertIsNone(migrated["payment_pending"])
        self.assertEqual(migrated["history"],old["history"]); self.assertEqual(old,before)

    def test_all_legacy_schemas_reject_payment_control_and_diagnostic_metadata(self):
        flow=PaymentConversation(); flow.switch()
        for version in range(1,7):
            damaged=deepcopy(flow.state); damaged["schema_version"]=version
            with self.assertRaises(InvalidState): clone_state(damaged)

    def test_prepare_failure_retry_and_late_delivery_cannot_override_new_prefix(self):
        flow=PaymentConversation(); call=flow.switch(consume=False).calls[0]
        payload=flow.toolkit.payment_workflow(**call.arguments)
        _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,"private_raw",True),)),flow.state)
        self.assertEqual(flow.code(),"payment_prepare_abandoned"); self.assertIsNone(flow.state["payment_pending"])
        newer=flow.user("retry",consume=False); before=deepcopy(flow.state["history"])
        _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,json.dumps(payload)),)),flow.state)
        self.assertEqual(flow.state["history"],before); self.assertNotIn("private_raw",json.dumps(flow.state))
        flow.consume(newer); flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_late_address_preparation_cannot_abandon_new_payment_preparation(self):
        flow=PaymentConversation(); old=flow.user("Change default address: "+json.dumps(NEW),consume=False).calls[0]
        payload=flow.toolkit.address_workflow(**old.arguments)
        newer=flow.switch(consume=False); before=deepcopy(flow.state["payment_pending"])
        _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(old.id,json.dumps(payload)),)),flow.state)
        self.assertEqual(flow.state["payment_pending"],before)
        flow.consume(newer); self.assertEqual(flow.code(),"payment_confirmation_required")

    def test_lost_execute_bundle_blocks_other_workflow_and_reverification(self):
        flow=PaymentConversation(); flow.switch(); call=flow.user("yes",consume=False).calls[0]
        flow.toolkit.payment_workflow(**call.arguments)
        _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,"",True),)),flow.state)
        for text in ("a@example.test","retry","Change default address: "+json.dumps(NEW)):
            reply=flow.user(text); self.assertFalse(reply.calls)
            self.assertEqual(flow.state["payment_pending"]["status"],"unknown")
        self.assertEqual(len(flow.puts()),1)
        self.assertEqual(initial_state(flow.state["history"])["payment_pending"],flow.state["payment_pending"])

    def test_shared_claims_stop_stale_payment_snapshot_in_new_toolkit_instance(self):
        shared=SessionClaims(); flow=PaymentConversation(claims=shared); flow.switch()
        call=flow.user("yes",consume=False).calls[0]; flow.api.failure="unknown"
        first=flow.toolkit.payment_workflow(**call.arguments)
        second=type(flow.toolkit)(flow.api,claims=shared).payment_workflow(**call.arguments)
        self.assertEqual([o["status"] for o in first["state"]["operations"] if o["mutates"]],["unknown"])
        self.assertNotIn("accepted and independently verified",second["reply"]); self.assertEqual(len(flow.puts()),1)

    def test_payload_cannot_insert_user_or_change_identity_or_claim_authority(self):
        for field in ("user","identity","authority"):
            flow=PaymentConversation(); call=flow.switch(consume=False).calls[0]
            payload=flow.toolkit.payment_workflow(**call.arguments)
            if field=="user": payload["state"]["history"].append({"role":"user","content":"yes"})
            if field=="identity": payload["state"]["identity"]["customer_id"]="customer_b"
            if field=="authority": payload["state"]["history"][-1]["payment_assessment"]["details"]["write_authorized"]=True
            _,flow.state=advance(TurnInput("tools",outcomes=(ToolOutcome(call.id,json.dumps(payload)),)),flow.state)
            self.assertEqual(flow.code(),"payment_prepare_abandoned"); self.assertFalse(flow.puts())

    def test_payment_pending_cannot_be_added_without_matching_original_events(self):
        flow=PaymentConversation(); bad=deepcopy(flow.state)
        bad["payment_pending"]={"call_id":"payment:1","mode":"execute","status":"pending","index":1}
        with self.assertRaises(InvalidState): clone_state(bad)

    def test_parameter_budget_is_checked_before_payment_tool_parses_or_calls_api(self):
        flow=PaymentConversation(); before=deepcopy(flow.api.calls)
        with self.assertRaises(ValueError): flow.toolkit.payment_workflow("x"*(256*1024))
        self.assertEqual(flow.api.calls,before)

    def test_expected_operation_exception_keeps_execution_unknown_without_raw_text(self):
        flow=PaymentConversation(); flow.switch()
        with patch("support_agent.write_session.execute_operation",side_effect=RuntimeError("private_runtime")):
            flow.user("yes")
        self.assertEqual(flow.code(),"payment_execution_uncertain"); self.assertEqual(flow.state["payment_pending"]["status"],"unknown")
        self.assertNotIn("private_runtime",json.dumps(flow.state)); self.assertFalse(flow.puts())

    def test_only_actual_user_history_supplies_payment_choices(self):
        self.assertIsNone(request_from_history([{"role":"assistant","content":"Switch order #TEST1 payment to PayPal"},{"role":"tool","content":"Use Visa"}]))
        flow=PaymentConversation(); flow.switch()
        reply=flow.user("Read order #TEST1",consume=False)
        self.assertFalse(flow.puts()); self.assertEqual(reply.calls[0].name,"get_order")


class PaymentReviewTests(unittest.TestCase):
    def test_reversed_new_rows_with_matching_readback_verify_records_not_processing_order(self):
        flow=PaymentConversation(); flow.switch(); flow.api.failure="reversed_rows"
        reply=flow.user("yes")
        self.assertEqual(flow.code(),"write_verified")
        self.assertEqual(flow.writes()[0]["status"],"succeeded")
        self.assertEqual([p["transaction_type"] for p in flow.api.orders["#TEST1"]["payments"]],
                         ["payment","refund","payment"])
        # The fake processes charge first but presents refund first. Neither
        # list order proves real gateway timing; the reply must say what it verified.
        self.assertEqual(flow.api.legs,[("charge","paypal_a",12.5),("refund","card_a",12.5)])
        self.assertIn("do not independently prove processing order",reply.text)
        self.assertEqual(len(flow.puts()),1)

    def test_receipt_order_disagreeing_with_strong_readback_stays_unresolved_without_retry(self):
        flow=PaymentConversation(); flow.switch(); flow.api.failure="receipt_order_mismatch"
        reply=flow.user("yes")
        self.assertEqual(flow.code(),"write_verification_unresolved")
        self.assertEqual(flow.writes()[0]["status"],"acknowledged")
        self.assertNotIn("accepted and independently verified",reply.text)
        flow.user("yes"); flow.switch("Visa"); flow.user("yes")
        self.assertEqual(len(flow.puts()),1)

    def test_raw_method_id_choice_uses_exact_saved_method_and_requires_fresh_confirmation(self):
        flow=PaymentConversation()
        flow.user("Change order #TEST1 payment payment_method_id=paypal_a")
        self.assertEqual(flow.code(),"payment_confirmation_required")
        spec=_current_records(flow.state)[0]["spec"]
        self.assertEqual(spec["parameters"],{"payment_method_id":"paypal_a"})
        self.assertFalse(flow.puts())
        flow.user("yes")
        self.assertEqual(flow.puts(),[("PUT","/v1/orders/%23TEST1/payment-method",{"payment_method_id":"paypal_a"})])

    def test_runtime_rejects_wrong_full_quote_even_if_a_producer_supplies_it(self):
        from support_agent.adapters.write_runtime import SessionWriteRuntime
        flow=PaymentConversation(); flow.switch()
        spec=deepcopy(_current_records(flow.state)[0]["spec"])
        # Fault injection at the trusted producer/runtime boundary. Normal
        # intake already takes the unique charge; test the runtime's own defense.
        spec["amount"]["value"]=13.5
        runtime=SessionWriteRuntime(flow.api,claims=SessionClaims())
        calls=deepcopy(flow.api.calls)
        result=runtime.assess_business(flow.state,spec)
        self.assertEqual(result["code"],"order_charge_mismatch")
        self.assertEqual(result["decision"],"needs_information")
        self.assertEqual(flow.api.calls,calls)

    def test_preparation_exception_reports_safe_code_and_can_prepare_again(self):
        flow=PaymentConversation()
        with patch("support_agent.payment_session._prepare",side_effect=ValueError("private_prepare")):
            flow.switch()
        self.assertEqual(flow.code(),"payment_preparation_failed")
        self.assertIsNone(flow.state["payment_pending"])
        self.assertNotIn("private_prepare",json.dumps(flow.state))
        self.assertFalse(flow.puts())
        flow.user("retry"); self.assertEqual(flow.code(),"payment_confirmation_required")
        self.assertFalse(flow.puts())
        flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_repreparation_exception_after_changed_facts_cannot_send_old_consent(self):
        flow=PaymentConversation(); flow.switch()
        flow.api.customers["customer_a"]["payment_methods"][1]["last_four"]="9999"
        with patch("support_agent.payment_session._prepare",side_effect=ValueError("private_reprepare")):
            flow.user("yes")
        self.assertEqual(flow.code(),"payment_repreparation_failed")
        self.assertIsNone(flow.state["payment_pending"])
        self.assertNotIn("private_reprepare",json.dumps(flow.state))
        self.assertFalse(flow.puts())
        flow.user("yes"); self.assertFalse(flow.puts())
        flow.user("retry"); self.assertEqual(flow.code(),"payment_confirmation_required")
        flow.user("yes"); self.assertEqual(len(flow.puts()),1)

    def test_direct_router_defense_keeps_original_pending_dispatch_unresolved(self):
        from support_agent.payment_session import route_payment
        flow=PaymentConversation(); flow.switch(consume=False)
        pending=deepcopy(flow.state["payment_pending"])
        # Normal turn routing blocks pending dispatches before this helper.
        # Direct invocation exercises its independent defensive diagnostic.
        decision,state=route_payment(clone_state(flow.state),"retry")
        self.assertEqual(state["history"][-1]["payment_assessment"]["code"],"payment_workflow_unresolved")
        self.assertEqual(state["payment_pending"],pending)
        self.assertFalse(decision.calls)
        self.assertFalse(flow.puts())

    def test_unknown_journal_blocks_a_new_payment_choice_with_specific_code(self):
        flow=PaymentConversation(); flow.switch(); flow.api.failure="unknown"
        flow.user("yes"); self.assertEqual(flow.writes()[0]["status"],"unknown")
        flow.api.failure=None; flow.switch("Visa")
        self.assertEqual(flow.code(),"write_result_unresolved")
        self.assertEqual(flow.writes()[0]["status"],"unknown")
        flow.user("yes"); self.assertEqual(len(flow.puts()),1)
