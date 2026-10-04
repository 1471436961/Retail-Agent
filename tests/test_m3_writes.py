"""M3.5 uses fake transport/runtime only; no production write capability."""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from test_m3_proposals import verified_state, specification, agree, address
from test_m3_tasks import prepared, two_orders, request, assessment
from support_agent.adapters.client_api import request_object
from support_agent.domain.rules import allow, need
from support_agent.domain.write_receipts import fulfillment_rule, normalize_receipt
from support_agent.proposals import present_proposal, present_proposals, confirmation_matches
from support_agent.state import SCHEMA_VERSION, InvalidState, clone_state, initial_state
from support_agent.tasks import present_task_plan, inspect_task_plan
from support_agent.write_session import WriteRuntime, WriteClaimConflict, claim_identity, execute_operation, reconcile_operation, refresh_proposal


def confirmed(action="shipping_address", status="pending"):
    state, api = verified_state(status=status)
    spec = specification(action)
    if action in {"modify_items", "exchange"}:
        spec["amount"]["value"] = -1.12
    _, state = present_proposal(state, spec)
    _, state = agree(state)
    return state, api, spec


def writes(state):
    return [o for o in state["operations"] if o["mutates"]]


class FakeRuntime(WriteRuntime):
    def __init__(self, api):
        super().__init__(api)
        self.sends, self.checkpoints = [], []
        self.status = 200
        self.error = None
        self.bad_body = None
        self.readback_failure = False
        self.no_effect = False
        self.checkpoint_failure = None
        self.claims = set()
        self.submission = allow("offline_authenticated_submission", "Synthetic trusted runtime only.")
        self.business = allow("offline_business_validation", "Synthetic workflow only; not classroom evidence.")

    def assess_submission(self, state, version, spec):
        return self.submission

    def assess_business(self, state, spec):
        return self.business

    def checkpoint(self, state):
        self.checkpoints.append(deepcopy(state))
        if len(self.checkpoints) == self.checkpoint_failure:
            raise OSError("synthetic checkpoint failure")

    def claim_sent(self, state, call_id):
        # In-memory protocol fake only. Production requires a durable atomic
        # store and authenticated submission; this is not that implementation.
        identity = claim_identity(state, call_id)
        if identity in self.claims:
            raise WriteClaimConflict("already claimed")
        self.claims.add(identity)
        self.checkpoint(state)
        return True

    def send(self, spec):
        self.sends.append(deepcopy(spec))
        assert writes(self.checkpoints[-1])[-1]["status"] == "sent"
        runtime = self

        class Transport:
            def request(self, method, path, body):
                if runtime.error:
                    raise runtime.error
                action, params, target = spec["action"], spec["parameters"], spec["target"]
                order = runtime.client_api.orders.get(target.get("order_id"))
                customer = runtime.client_api.customers[target["customer_id"]]
                if action == "default_shipping_address":
                    result = {"customer_id": target["customer_id"], "default_shipping_address": params}
                elif action == "shipping_address":
                    result = {"order_id": target["order_id"], "shipping_address": params}
                elif action == "cancel":
                    refunds = [{**p, "transaction_type":"refund"} for p in spec["amount"]["rows"]]
                    result = {"order_id": target["order_id"], "status": "cancelled", "cancellation": params, "payments": order["payments"] + refunds}
                elif action == "exchange":
                    result = {"order_id": target["order_id"], "status": "exchange requested", "exchange": {**params, "price_difference": spec["amount"]["value"]}}
                elif action == "modify_items":
                    items = deepcopy(order["items"])
                    for pair in params["replacements"]:
                        item = next(i for i in items if i["item_id"] == pair["existing_item_id"])
                        variant = next(i for i in runtime.client_api.products[item["product_id"]]["items"] if i["item_id"] == pair["replacement_item_id"])
                        item.update(item_id=variant["item_id"], price=variant["price"], options=variant["options"])
                    diff = spec["amount"]["value"]
                    payment = {"transaction_type":"payment" if diff>0 else "refund", "amount":abs(diff), "payment_method_id":params["payment_method_id"]}
                    result = {"order_id": target["order_id"], "status": "pending (items modified)", "items": items, "payments": order["payments"] + ([payment] if diff else [])}
                else:
                    refunds = [{**p,"transaction_type":"refund"} for p in spec["amount"]["refund_rows"]]
                    result = {"order_id": target["order_id"], "payments": order["payments"] + [{"transaction_type":"payment", "amount":spec["amount"]["value"], "payment_method_id":params["payment_method_id"]}] + refunds}
                if runtime.status == 200 and not runtime.no_effect:
                    (customer if action == "default_shipping_address" else order).update(deepcopy(result))
                if runtime.readback_failure:
                    runtime.client_api.orders[target["order_id"]]["customer_id"] = "another_customer"
                return SimpleNamespace(status_code=runtime.status, body=deepcopy(runtime.bad_body if runtime.bad_body is not None else result))

        return request_object(Transport(), "PUT", "/offline/operation", body=spec["parameters"], mutates=True)


class PreflightTests(unittest.TestCase):
    def test_default_runtime_cannot_send_a_confirmed_proposal(self):
        state, api, spec = confirmed()
        before = deepcopy(api.calls)
        result, updated = execute_operation(state, 1, spec)
        self.assertEqual(result["code"], "write_runtime_required")
        self.assertEqual(updated, state)
        self.assertEqual(api.calls, before)

    def test_base_runtime_requires_submission_provenance_before_any_refresh(self):
        state, api, spec = confirmed()
        before = deepcopy(api.calls)
        result, updated = execute_operation(state, 1, spec, WriteRuntime(api))
        self.assertEqual(result["code"], "submission_contract_required")
        self.assertEqual(api.calls, before)
        self.assertFalse(writes(updated))

    def test_missing_partial_and_conditional_consent_do_not_read_or_send(self):
        for text in ("not yet", "yes if cheaper", "only the address"):
            state, api = verified_state()
            spec = specification()
            _, state = present_proposals(state, [spec])
            _, state = agree(state, text)
            runtime = FakeRuntime(api)
            before = deepcopy(api.calls)
            result, _ = execute_operation(state, 1, spec, runtime)
            self.assertNotEqual(result["decision"], "allow")
            self.assertFalse(runtime.sends)
            self.assertEqual(api.calls, before)

    def test_successful_refresh_preserves_equal_facts_and_does_not_authorize_write(self):
        state, api, spec = confirmed()
        before = deepcopy(state)
        result, updated = refresh_proposal(state, 1, spec, api)
        self.assertEqual(result["code"], "write_preflight_checked")
        self.assertFalse(result["details"]["write_authorized"])
        self.assertEqual(len(result["details"]["read_ids"]), 2)
        self.assertTrue(confirmation_matches(updated, 1, spec))
        self.assertEqual(state, before)

    def test_order_change_after_consent_stops_old_version(self):
        state, api, spec = confirmed()
        api.orders["#TEST1"]["shipping_address"]["city"] = "Changed"
        runtime = FakeRuntime(api)
        result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "facts_changed")
        self.assertFalse(runtime.sends)
        self.assertFalse(confirmation_matches(updated, 1, spec))

    def test_profile_balance_change_stops_old_consent(self):
        state, api = verified_state()
        api.customers["customer_a"]["payment_methods"].append({"id":"gift", "source":"gift_card", "balance":50})
        from support_agent.adapters.read_api import verify_customer
        from support_agent.protocol import ToolAction, ToolOutcome, Decision
        from support_agent.read_session import bind_arguments, record_decision, consume_results
        from support_agent.state import result_history
        call=ToolAction("gift-profile-fixture","read_customer_profile",bind_arguments("read_customer_profile",{},state))
        record_decision(state,Decision(calls=(call,)))
        outcome=ToolOutcome(call.id,json.dumps(verify_customer(api,**call.arguments)))
        status,_=consume_results(state,(outcome,));state["history"].append(result_history((outcome,),status=status))
        spec=specification("payment_method");spec["parameters"]["payment_method_id"]="gift"
        _,state=present_proposal(state,spec);_,state=agree(state)
        api.customers["customer_a"]["payment_methods"][-1]["balance"]=0
        runtime = FakeRuntime(api)
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "facts_changed")
        self.assertFalse(runtime.sends)

    def test_catalog_price_change_is_read_and_invalidates_consent(self):
        state, api, spec = confirmed("modify_items")
        api.products["product_mug"]["items"][1]["price"] = 99
        runtime = FakeRuntime(api)
        result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "facts_changed")
        self.assertFalse(runtime.sends)
        self.assertEqual(updated["operations"][-1]["name"], "get_product")

    def test_removed_owned_reference_prevents_order_get(self):
        state, api, spec = confirmed()
        api.customers["customer_a"]["order_ids"].remove("#TEST1")
        start = len(api.calls)
        runtime = FakeRuntime(api)
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "refresh_scope_changed")
        self.assertFalse(any(path.startswith("/v1/orders/") for method, path, body in api.calls[start:]))
        self.assertFalse(runtime.sends)

    def test_failed_refresh_has_no_old_body_fallback(self):
        state, api, spec = confirmed()
        runtime = FakeRuntime(api)
        with patch.object(api, "request", side_effect=TimeoutError("private raw error")):
            result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "refresh_failed")
        self.assertNotIn("private raw error", json.dumps(updated))
        self.assertFalse(runtime.sends)

    def test_runtime_business_gate_still_blocks_after_refresh(self):
        state, api, spec = confirmed("payment_method")
        runtime = FakeRuntime(api)
        runtime.business = need("current_method_unproven", "Current payment method needs proof.")
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "current_method_unproven")
        self.assertFalse(runtime.sends)

    def test_malformed_runtime_assessment_is_denied(self):
        state, api, spec = confirmed()
        runtime = FakeRuntime(api)
        runtime.submission = True
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "invalid_runtime_assessment")
        self.assertTrue(result["details"]["input_error"])
        self.assertFalse(runtime.sends)

    def test_refresh_budget_blocks_before_any_partial_refresh(self):
        state, api, spec = confirmed()
        state["tool_calls_since_user"] = 11
        runtime = FakeRuntime(api)
        start = len(api.calls)
        result, _ = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "refresh_budget_exceeded")
        self.assertEqual(len(api.calls), start)
        self.assertFalse(runtime.sends)

    def test_pending_fulfillment_units_stop_write_without_inventing_shipped(self):
        state, api = verified_state()
        api.orders["#TEST1"]["fulfillments"] = [{"item_ids":["item_blue"], "tracking_id":[]}]
        from test_m3_proposals import accept_read
        state = accept_read(state, api, "get_order", {"order_id":"#TEST1"}, "fulfillment-fixture")
        spec = specification()
        _, state = present_proposal(state, spec)
        _, state = agree(state)
        runtime = FakeRuntime(api)
        result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "fulfillment_requires_review")
        self.assertFalse(runtime.sends)
        self.assertNotIn("shipped", updated)

    def test_tracking_labels_alone_preserve_pending_eligibility(self):
        order = {"status":"pending", "items":[{"item_id":"x"}], "fulfillments":[{"item_ids":[], "tracking_id":["label"]}]}
        self.assertEqual(fulfillment_rule(order,"shipping_address")["code"], "no_fulfillment_conflict")

    def test_uncontracted_shipping_fields_stop_without_interpreting_them(self):
        for extension in ({"shipped":True},{"shipped":False}):
            order={"status":"pending","items":[{"item_id":"x"}],"fulfillments":[],**extension}
            self.assertEqual(fulfillment_rule(order,"cancel")["code"],"undocumented_fulfillment_fact")
        order={"status":"pending","items":[{"item_id":"x"}],"fulfillments":[{"item_ids":[],"tracking_id":[],"status":"shipped"}]}
        self.assertEqual(fulfillment_rule(order,"shipping_address")["code"],"undocumented_fulfillment_fact")

    def test_fulfillment_unknown_or_excess_units_are_conflicts(self):
        for ids in (["missing"], ["x","x"]):
            order = {"status":"pending", "items":[{"item_id":"x"}], "fulfillments":[{"item_ids":ids, "tracking_id":[]}]}
            self.assertEqual(fulfillment_rule(order,"cancel")["code"], "fulfillment_items_conflict")

    def test_unrounded_item_quote_requires_new_complete_proposal(self):
        state,api=verified_state();spec=specification("modify_items")
        _,state=present_proposal(state,spec);_,state=agree(state)
        runtime=FakeRuntime(api)
        result,_=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"price_difference_mismatch")
        self.assertFalse(runtime.sends)

    def test_runtime_assessment_exception_is_safe_and_does_not_send(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api)
        with patch.object(runtime,"assess_submission",side_effect=RuntimeError("private provider data")):
            result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"runtime_assessment_failed")
        self.assertFalse(runtime.sends)
        self.assertNotIn("private provider data",json.dumps(updated))


class WriteLifecycleTests(unittest.TestCase):
    def test_send_checkpoint_receipt_and_strong_readback_complete_one_operation(self):
        state, api, spec = confirmed()
        runtime = FakeRuntime(api)
        result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "write_verified")
        self.assertEqual(len(runtime.sends), 1)
        self.assertEqual([writes(s)[-1]["status"] for s in runtime.checkpoints], ["sent","acknowledged","succeeded"])
        self.assertEqual(writes(updated)[0]["status"], "succeeded")
        self.assertFalse(result["details"]["write_authorized"])
        self.assertEqual(initial_state(updated["history"])["operations"], updated["operations"])

    def test_timeout_is_unknown_and_repeated_entry_sends_at_most_once(self):
        state, api, spec = confirmed()
        runtime = FakeRuntime(api)
        runtime.error = TimeoutError("raw private data")
        result, updated = execute_operation(state, 1, spec, runtime)
        self.assertEqual(result["code"], "write_result_unknown")
        self.assertEqual(writes(updated)[0]["status"], "unknown")
        again, _ = execute_operation(updated, 1, spec, runtime)
        self.assertEqual(again["code"], "write_already_attempted")
        self.assertEqual(len(runtime.sends), 1)
        self.assertNotIn("raw private data", json.dumps(updated))

    def test_http_errors_classify_definite_failure_and_unknown_without_retry(self):
        for status, expected in ((400,"failed"),(409,"failed"),(422,"failed"),(500,"unknown"),(502,"unknown"),(201,"unknown")):
            with self.subTest(status=status):
                state, api, spec = confirmed()
                runtime = FakeRuntime(api); runtime.status = status
                result, updated = execute_operation(state, 1, spec, runtime)
                self.assertEqual(writes(updated)[0]["status"], expected)
                execute_operation(updated, 1, spec, runtime)
                self.assertEqual(len(runtime.sends), 1)

    def test_unusable_success_body_is_unknown_not_failed(self):
        for body in ({}, {"order_id":"other", "shipping_address":address()}, {"order_id":"#TEST1", "shipping_address":{}}):
            state, api, spec = confirmed()
            runtime = FakeRuntime(api); runtime.bad_body = body
            result, updated = execute_operation(state,1,spec,runtime)
            self.assertEqual(result["code"], "write_result_unknown")
            self.assertIsNone(writes(updated)[0]["receipt"])
            self.assertEqual(len(runtime.sends),1)

    def test_receipt_alone_does_not_complete_when_readback_fails(self):
        state, api, spec = confirmed()
        runtime = FakeRuntime(api); runtime.readback_failure=True
        result, updated = execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"], "write_verification_unresolved")
        self.assertEqual(writes(updated)[0]["status"], "acknowledged")
        self.assertEqual(len(runtime.sends),1)

    def test_mismatching_readback_does_not_accept_partial_verified_event(self):
        state, api, spec = confirmed()
        spec["parameters"]["city"]="Newcity"
        _, state = present_proposal(state,spec); _,state=agree(state)
        runtime=FakeRuntime(api); runtime.no_effect=True
        result,updated=execute_operation(state,2,spec,runtime)
        self.assertEqual(result["code"],"write_verification_unresolved")
        self.assertEqual(writes(updated)[0]["status"],"acknowledged")
        self.assertFalse(any(e.get("write_event",{}).get("kind")=="verified" for e in updated["history"]))
        self.assertEqual(clone_state(updated),updated)

    def test_checkpoint_failure_before_send_performs_zero_send(self):
        state, api, spec = confirmed()
        runtime=FakeRuntime(api); runtime.checkpoint_failure=1
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"checkpoint_unresolved")
        self.assertEqual(writes(updated)[0]["status"],"sent")
        self.assertFalse(runtime.sends)
        restored=initial_state(updated["history"])
        again,_=execute_operation(restored,1,spec,runtime)
        self.assertEqual(again["code"],"write_already_attempted")
        self.assertFalse(runtime.sends)

    def test_checkpoint_failure_after_send_preserves_receipt_without_resend(self):
        state,api,spec=confirmed(); runtime=FakeRuntime(api); runtime.checkpoint_failure=2
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"checkpoint_unresolved")
        self.assertEqual(writes(updated)[0]["status"],"acknowledged")
        execute_operation(updated,1,spec,runtime)
        self.assertEqual(len(runtime.sends),1)

    def test_verified_checkpoint_failure_keeps_effect_but_does_not_release_dependency(self):
        state,api,specs=prepared("shipping_address","modify_items")
        runtime=FakeRuntime(api);runtime.checkpoint_failure=3
        result,updated=execute_operation(state,1,specs[0],runtime)
        self.assertEqual(result["code"],"checkpoint_unresolved")
        self.assertEqual(writes(updated)[0]["status"],"succeeded")
        self.assertTrue(writes(updated)[0]["persistence_unresolved"])
        self.assertNotEqual(assessment(updated,"shipping_address")["code"],"task_completed")
        result,_=reconcile_operation(updated,writes(updated)[0]["call_id"],runtime)
        self.assertEqual(result["code"],"checkpoint_unresolved")
        self.assertEqual(len(runtime.sends),1)
        self.assertEqual(writes(initial_state(updated["history"])),writes(updated))

    def test_default_address_receipt_is_a_separate_customer_record(self):
        state,api,spec=confirmed("default_shipping_address"); runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertNotIn("order_id",writes(updated)[0]["spec"]["target"])

    def test_cancellation_receipt_does_not_claim_refund_arrival(self):
        state,api,spec=confirmed("cancel"); runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(writes(updated)[0]["receipt"]["status"],"cancelled")
        self.assertNotIn("refund_total",writes(updated)[0])

    def test_exchange_receipt_preserves_ordered_replacements_and_signed_difference(self):
        state,api,spec=confirmed("exchange",status="delivered"); runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(writes(updated)[0]["receipt"]["exchange"]["price_difference"],-1.12)

    def test_item_modification_receipt_validates_lock_state_and_readback(self):
        state,api,spec=confirmed("modify_items"); runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(writes(updated)[0]["receipt"]["items"][0]["item_id"],"item_red")

    def test_payment_receipt_needs_new_charge_and_each_original_refund(self):
        state,api,spec=confirmed("payment_method");runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        suffix=writes(updated)[0]["receipt"]["payments"][2:]
        self.assertEqual([p["transaction_type"] for p in suffix],["payment","refund","refund"])
        self.assertEqual([p["amount"] for p in suffix],[14.5,12.5,2])

    def test_duplicate_charge_refunds_cannot_be_collapsed_in_receipt_verification(self):
        from support_agent.domain.write_receipts import receipt_matches_readback
        state,api,spec=confirmed("cancel")
        before={"order":deepcopy(api.orders["#TEST1"]),"customer":deepcopy(api.customers["customer_a"]),"catalog":[]}
        body={"order_id":"#TEST1","status":"cancelled","cancellation":spec["parameters"],"payments":before["order"]["payments"] + [{"transaction_type":"refund","amount":14.5,"payment_method_id":"card_a"}]}
        after={**before,"order":{**before["order"],**body}}
        self.assertFalse(receipt_matches_readback(spec,body,after,before))

    def test_optional_null_second_address_line_is_normalized_without_inventing_values(self):
        spec=specification();body={"order_id":"#TEST1","shipping_address":address()}
        del body["shipping_address"]["address_line_2"]
        self.assertEqual(normalize_receipt(spec,body)["shipping_address"],spec["parameters"])
        self.assertNotIn("address_line_2",body["shipping_address"])

    def test_exchange_bool_difference_is_not_a_numeric_receipt(self):
        spec=specification("exchange");spec["amount"]["value"]=1
        body={"order_id":"#TEST1","status":"exchange requested","exchange":{**spec["parameters"],"price_difference":True}}
        with self.assertRaises(ValueError): normalize_receipt(spec,body)

    def test_late_readback_can_verify_acknowledged_receipt_without_another_send(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api);runtime.readback_failure=True
        _,updated=execute_operation(state,1,spec,runtime)
        api.orders["#TEST1"]["customer_id"]="customer_a"
        restored=initial_state(updated["history"])
        result,reconciled=reconcile_operation(restored,writes(restored)[0]["call_id"],runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(writes(reconciled)[0]["status"],"succeeded")
        self.assertEqual(len(runtime.sends),1)
        result,_=reconcile_operation(reconciled,writes(reconciled)[0]["call_id"],runtime)
        self.assertEqual(result["code"],"write_already_verified")

    def test_matching_backend_state_cannot_replace_an_unknown_receipt(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api);runtime.error=TimeoutError()
        _,updated=execute_operation(state,1,spec,runtime)
        api.orders["#TEST1"]["shipping_address"]=deepcopy(spec["parameters"])
        before=deepcopy(api.calls)
        result,reconciled=reconcile_operation(updated,writes(updated)[0]["call_id"],runtime)
        self.assertEqual(result["code"],"write_result_unknown")
        self.assertEqual(api.calls,before)
        self.assertEqual(writes(reconciled)[0]["status"],"unknown")


class WriteRecoveryAndTaskTests(unittest.TestCase):
    def test_fixed_schema4_fixture_migrates_without_creating_write_evidence(self):
        fixture=json.loads((Path(__file__).parent/"fixtures/m3_schema4_state.json").read_text(encoding="utf-8"))
        legacy=fixture["state"]
        self.assertEqual(legacy["schema_version"],4)
        updated=clone_state(legacy)
        self.assertEqual(updated["schema_version"],SCHEMA_VERSION)
        self.assertEqual(updated["history"],legacy["history"])
        self.assertEqual(updated["proposals"],legacy["proposals"])
        self.assertFalse(writes(updated))

    def test_legacy_schema_cannot_claim_new_journal_or_mutating_operations(self):
        state,api,spec=confirmed(); runtime=FakeRuntime(api)
        _,updated=execute_operation(state,1,spec,runtime)
        for version in (1,2,3,4):
            damaged=deepcopy(updated); damaged["schema_version"]=version
            with self.assertRaises(InvalidState): clone_state(damaged)

    def test_tampered_operation_status_receipt_and_refresh_ids_are_rejected(self):
        state,api,spec=confirmed(); runtime=FakeRuntime(api)
        _,updated=execute_operation(state,1,spec,runtime)
        for field,value in (("status","unknown"),("receipt",{}),("read_ids",[]),("sent_index",0),("verified_read_ids",[])):
            damaged=deepcopy(updated); next(o for o in damaged["operations"] if o["mutates"])[field]=value
            with self.subTest(field=field), self.assertRaises(InvalidState): clone_state(damaged)

    def test_mixed_write_and_proposal_metadata_is_rejected(self):
        state,api,spec=confirmed(); runtime=FakeRuntime(api)
        _,updated=execute_operation(state,1,spec,runtime)
        entry=next(e for e in updated["history"] if "write_event" in e)
        entry["proposal_ack"]={}
        with self.assertRaises(InvalidState): clone_state(updated)

    def test_model_flags_do_not_enable_the_default_runtime(self):
        state,api,spec=confirmed(); state["write_authorized"]=True; state["delivery_verified"]=True
        with self.assertRaisesRegex(InvalidState, "Authorization flags"):
            execute_operation(state,1,spec,{"confirmed":True})

    def test_verified_prerequisite_releases_dependency_only_after_new_fact_bound_proposal(self):
        state,api,specs=prepared("shipping_address","modify_items")
        runtime=FakeRuntime(api)
        result,updated=execute_operation(state,1,specs[0],runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(assessment(updated,"shipping_address")["code"],"task_completed")
        _,updated=present_proposals(updated,[specs[1]])
        _,updated=agree(updated)
        self.assertEqual(assessment(updated,"modify_items")["code"],"preflight_candidate")

    def test_unknown_prerequisite_never_releases_dependent_write(self):
        state,api,specs=prepared("shipping_address","modify_items")
        runtime=FakeRuntime(api); runtime.error=TimeoutError()
        _,updated=execute_operation(state,1,specs[0],runtime)
        result,_=execute_operation(updated,2,specs[1],runtime)
        self.assertEqual(result["code"],"write_result_unresolved")
        self.assertEqual(len(runtime.sends),1)

    def test_cross_order_unknown_does_not_block_an_independent_confirmed_scope(self):
        state,api=two_orders()
        specs=[specification(),specification()]; specs[1]["target"]["order_id"]="#TEST3"
        _,state=present_proposals(state,specs); _,state=agree(state)
        runtime=FakeRuntime(api); runtime.error=TimeoutError()
        _,updated=execute_operation(state,1,specs[0],runtime)
        runtime.error=None
        result,updated=execute_operation(updated,2,specs[1],runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual([o["status"] for o in writes(updated)],["unknown","succeeded"])

    def test_dependency_guard_and_conflicting_plan_prevent_send(self):
        for actions, version in ((('shipping_address','modify_items'),2),(('shipping_address','cancel'),1)):
            if 'cancel' in actions:
                state,api,specs=prepared("shipping_address")
                _,state=present_task_plan(state,[request(a) for a in actions])
            else:
                state,api,specs=prepared(*actions)
            runtime=FakeRuntime(api)
            result,_=execute_operation(state,version,specs[version-1],runtime)
            self.assertIn(result["code"],{"dependency_result_required","same_order_cancel_conflict"})
            self.assertFalse(runtime.sends)

    def test_completed_old_plan_does_not_complete_a_new_request_plan(self):
        state,api,specs=prepared("shipping_address")
        _,updated=execute_operation(state,1,specs[0],FakeRuntime(api))
        _,updated=present_task_plan(updated,[request()])
        self.assertNotEqual(assessment(updated,"shipping_address")["code"],"task_completed")

    def test_released_dependency_can_send_and_recover_its_own_verified_result(self):
        state,api,specs=prepared("shipping_address","modify_items")
        runtime=FakeRuntime(api)
        _,updated=execute_operation(state,1,specs[0],runtime)
        specs[1]["amount"]["value"]=-1.12
        _,updated=present_proposals(updated,[specs[1]]);_,updated=agree(updated)
        version=updated["proposals"][-1]["version"]
        result,updated=execute_operation(updated,version,specs[1],runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(len(runtime.sends),2)
        restored=initial_state(updated["history"])
        self.assertEqual(writes(restored),writes(updated))
        self.assertEqual(assessment(restored,"modify_items")["code"],"task_completed")

    def test_new_version_cannot_bypass_unknown_write_on_same_record(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api);runtime.error=TimeoutError()
        _,updated=execute_operation(state,1,spec,runtime)
        spec=deepcopy(spec);spec["parameters"]["city"]="New request"
        _,updated=present_proposal(updated,spec);_,updated=agree(updated)
        result,_=execute_operation(updated,2,spec,runtime)
        self.assertEqual(result["code"],"write_result_unresolved")
        self.assertEqual(len(runtime.sends),1)

    def test_runtime_assessment_and_send_receive_unaliased_bound_specifications(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api)
        original=deepcopy(spec)
        def mutate_assessment(state,spec):
            spec["parameters"]["city"]="Attempted mutation"
            return allow("synthetic_gate","This does not change bound parameters.")
        with patch.object(runtime,"assess_business",side_effect=mutate_assessment):
            result,updated=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_verified")
        self.assertEqual(runtime.sends[0],original)
        self.assertEqual(spec,original)

    def test_three_remaining_task_fields_cannot_be_forged(self):
        state,api,specs=prepared("shipping_address")
        for key,value in (("action","cancel"),("conflicts",[{"task_id":"fake","code":"fake"}]),("plan_index",0)):
            damaged=deepcopy(state);damaged["tasks"][0][key]=value
            with self.subTest(key=key),self.assertRaises(InvalidState):clone_state(damaged)

    def test_stale_original_state_cannot_send_again_after_durable_claim(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api);runtime.error=TimeoutError()
        _,updated=execute_operation(state,1,spec,runtime)
        result,blocked=execute_operation(state,1,spec,runtime)
        self.assertEqual(result["code"],"write_already_claimed")
        self.assertEqual(len(runtime.sends),1)
        self.assertEqual(len(runtime.claims),1)
        self.assertEqual(writes(blocked)[0]["status"],"sent")

    def test_late_failed_refresh_cannot_replace_newest_refresh_ids_in_sent_journal(self):
        state,api,spec=confirmed();runtime=FakeRuntime(api);runtime.checkpoint_failure=1
        _,updated=execute_operation(state,1,spec,runtime)
        from support_agent.write_session import restore_write_event, InvalidWrite
        sent=deepcopy(next(e for e in updated["history"] if e.get("write_event",{}).get("kind")=="sent"))
        prefix=initial_state(updated["history"][:writes(updated)[0]["sent_index"]])
        from support_agent.protocol import ToolAction,Decision,ToolOutcome
        from support_agent.read_session import bind_arguments,record_decision,consume_results
        from support_agent.state import result_history
        call=ToolAction("later-failed-order","get_order",bind_arguments("get_order",{"order_id":"#TEST1"},prefix))
        record_decision(prefix,Decision(calls=(call,)))
        outcome=ToolOutcome(call.id,"",True);status,_=consume_results(prefix,(outcome,))
        prefix["history"].append(result_history((outcome,),status=status))
        index=len(prefix["history"])
        sent["write_event"]["call_id"]=f"write:{index}:1"
        sent["content"]="Operation journal: "+json.dumps(sent["write_event"],sort_keys=True,ensure_ascii=False)
        prefix["history"].append(sent)
        with self.assertRaisesRegex(InvalidWrite,"later attempt"):
            restore_write_event(prefix,index)

    def test_matching_lock_receipt_with_wrong_replacement_does_not_complete(self):
        from support_agent.domain.write_receipts import receipt_matches_readback
        state,api,spec=confirmed("modify_items")
        from support_agent.proposals import _scope_facts
        before=_scope_facts(state["history"],spec)
        body={"order_id":"#TEST1","status":"pending (items modified)","items":before["order"]["items"],"payments":before["order"]["payments"]}
        after={**before,"order":{**before["order"],**body}}
        self.assertFalse(receipt_matches_readback(spec,body,after,before))


if __name__ == "__main__":
    unittest.main()
