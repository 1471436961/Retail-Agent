"""M3.4 graph and actual session planning; fake reads, no business writes."""
import json
import sys
import unittest
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from test_m3_proposals import verified_state, specification, accept_read, agree
from support_agent.adapters.read_api import verify_customer
from support_agent.domain.task_graph import InvalidTaskPlan, build_task_graph, normalize_requests
from support_agent.protocol import Decision, ToolAction, ToolOutcome, TurnInput, InvalidAction, decision_from_candidate
from support_agent.proposals import present_proposals, confirmation_matches
from support_agent.read_session import bind_arguments, record_decision
from support_agent.state import SCHEMA_VERSION, InvalidState, clone_state, initial_state
from support_agent.tasks import inspect_task_plan, present_task_plan
from support_agent.turns import advance


def request(action="shipping_address", order_id="#TEST1"):
    target = {"customer_id": "customer_a"}
    if action != "default_shipping_address": target["order_id"] = order_id
    return {"action": action, "target": target}


def assessment(state, action, order_id="#TEST1"):
    result = inspect_task_plan(state)
    if result["code"] != "task_plan_assessed": raise AssertionError(result)
    found = [n for n in result["details"]["tasks"] if n["action"] == action and n["target"] == request(action, order_id)["target"]]
    if len(found) != 1: raise AssertionError("Expected one exact task scope")
    return found[0]["assessment"]


def prepared(*actions, status="pending"):
    state, api = verified_state(status=status)
    _, state = present_task_plan(state, [request(a) for a in actions])
    specs = [specification(a) for a in actions]
    _, state = present_proposals(state, specs)
    _, state = agree(state)
    return state, api, specs


def two_orders():
    state, api = verified_state()
    api.customers["customer_a"]["order_ids"].append("#TEST3")
    api.orders["#TEST3"] = deepcopy(api.orders["#TEST1"])
    api.orders["#TEST3"]["order_id"] = "#TEST3"
    call = ToolAction("profile-two-orders", "read_customer_profile", bind_arguments("read_customer_profile", {}, state))
    record_decision(state, Decision(calls=(call,)))
    body = verify_customer(api, **call.arguments)
    _, state = advance(TurnInput(kind="tools", outcomes=(ToolOutcome(call.id,json.dumps(body)),)),state)
    state = accept_read(state,api,"get_order",{"order_id":"#TEST3"},"order-three")
    return state, api


class TaskGraphTests(unittest.TestCase):
    def test_same_order_dependencies_are_independent_of_request_order(self):
        for actions in permutations(("modify_items", "shipping_address", "payment_method")):
            nodes = build_task_graph([request(a) for a in actions], 8, 2)
            by_action = {n["action"]:n for n in nodes}
            self.assertEqual([n["action"] for n in nodes], list(actions))
            self.assertEqual(set(by_action["modify_items"]["depends_on"]), {by_action[a]["id"] for a in ("shipping_address","payment_method")})
            self.assertFalse(by_action["shipping_address"]["depends_on"])
            self.assertFalse(by_action["payment_method"]["depends_on"])
            self.assertFalse(any(n["conflicts"] for n in nodes))

    def test_cancel_conflicts_with_every_other_same_order_action_symmetrically(self):
        for action in ("shipping_address","payment_method","modify_items","return","exchange"):
            nodes = build_task_graph([request(action),request("cancel")],3,1)
            for i,node in enumerate(nodes):
                self.assertEqual(node["conflicts"],[{"task_id":nodes[1-i]["id"],"code":"same_order_cancel_conflict"}])

    def test_return_and_exchange_conflict_before_either_is_submitted(self):
        nodes = build_task_graph([request("return"),request("exchange")],4,2)
        self.assertEqual([n["conflicts"][0]["code"] for n in nodes],["same_order_return_exchange_conflict"]*2)
        self.assertFalse(any(n["depends_on"] for n in nodes))

    def test_independent_orders_and_default_address_have_no_invented_edges(self):
        nodes = build_task_graph([request("modify_items"),request("shipping_address","#TEST3"),request("default_shipping_address")],7,1)
        self.assertTrue(all(not n["depends_on"] and not n["conflicts"] for n in nodes))

    def test_graph_preserves_raw_order_ids_and_customer_boundaries(self):
        other = request("cancel"); other["target"]["customer_id"]="customer_b"
        nodes=build_task_graph([request(),other],9,3)
        self.assertEqual(nodes[0]["target"]["order_id"],"#TEST1")
        self.assertFalse(any(n["conflicts"] for n in nodes))
        self.assertEqual(nodes[0]["id"],"task:9:1")

    def test_duplicate_action_target_cannot_split_a_one_shot_task(self):
        for action in ("modify_items","exchange","return","shipping_address"):
            with self.subTest(action=action),self.assertRaisesRegex(InvalidTaskPlan,"Duplicate scopes"):
                build_task_graph([request(action),request(action)],5,1)

    def test_malformed_task_inputs_are_not_business_missing_information(self):
        for inputs in (None,[],(),[True],[{"action":"transfer","target":{"customer_id":"customer_a"}}],
                       [dict(request(), confirmed=True)],[dict(request(),depends_on=[])],
                       [{"action":"shipping_address","target":{"customer_id":True,"order_id":"#TEST1"}}],
                       [{"action":"return","target":{"customer_id":"customer_a","order_id":1}}]):
            with self.subTest(inputs=inputs),self.assertRaises(InvalidTaskPlan):normalize_requests(inputs)

    def test_graph_is_deterministic_json_and_owns_inputs_and_outputs(self):
        requests=[request("modify_items"),request()]; original=deepcopy(requests)
        one=build_task_graph(requests,4,1); two=build_task_graph(requests,4,1)
        self.assertEqual(one,two);self.assertEqual(requests,original)
        one[0]["target"]["customer_id"]="changed"
        self.assertEqual(requests,original);self.assertEqual(two[0]["target"],original[0]["target"])
        self.assertEqual(json.loads(json.dumps(two,allow_nan=False)),two)

    def test_indices_reject_boolean_negative_and_noninteger_values(self):
        for value in (True,-1,1.0,None):
            for indices in ((value,1),(1,value)):
                with self.subTest(indices=indices),self.assertRaises(InvalidTaskPlan):build_task_graph([request()],*indices)


class TaskSessionTests(unittest.TestCase):
    def test_internal_plan_binds_actual_user_and_has_no_confirmation_effect(self):
        state,_=verified_state();original=deepcopy(state)
        decision,planned=present_task_plan(state,[request("modify_items"),request()])
        self.assertFalse(decision.calls);self.assertIn("not a confirmation recap",decision.text)
        self.assertIn("Requires verified completion of task(s) 2",decision.text)
        index=planned["tasks"][0]["request_index"]
        self.assertEqual(planned["history"][index]["role"],"user")
        self.assertEqual(planned["proposals"],[]);self.assertEqual(state,original)
        self.assertEqual(planned["operations"], original["operations"])
        self.assertEqual(planned["history"][:-1], original["history"])
        self.assertEqual(assessment(planned,"shipping_address")["code"],"proposal_required")

    def test_confirmation_does_not_complete_same_order_dependencies(self):
        state,api,specs=prepared("modify_items","shipping_address","payment_method")
        self.assertTrue(all(confirmation_matches(state,i,s) for i,s in enumerate(specs,1)))
        self.assertEqual(assessment(state,"modify_items")["code"],"dependency_result_required")
        for action in ("shipping_address","payment_method"):
            gate=assessment(state,action)
            self.assertEqual(gate["code"],"preflight_candidate");self.assertFalse(gate["details"]["write_authorized"])
        result=inspect_task_plan(state)
        self.assertFalse(result["details"]["write_authorized"])
        self.assertTrue(all(n["assessment"]["details"]["write_authorized"] is False for n in result["details"]["tasks"]))

    def test_withdrawn_prerequisite_blocks_dependent_without_revoking_its_consent(self):
        state,api,specs=prepared("modify_items","shipping_address")
        _,state=agree(state,"withdraw operation 2")
        self.assertTrue(confirmation_matches(state,1,specs[0]))
        self.assertEqual(assessment(state,"shipping_address")["code"],"proposal_withdrawn")
        gate=assessment(state,"modify_items")
        self.assertEqual(gate["code"],"dependency_blocked")
        self.assertEqual(gate["details"]["depends_on"],state["tasks"][0]["depends_on"])
        self.assertEqual(inspect_task_plan(state)["details"]["preflight_candidates"],[])

    def test_standalone_item_modification_has_no_unrequested_address_dependency(self):
        state,api,_=prepared("modify_items")
        self.assertEqual(state["tasks"][0]["depends_on"],[])
        self.assertEqual(assessment(state,"modify_items")["code"],"preflight_candidate")

    def test_invalid_plan_requests_leave_existing_plan_and_confirmations_untouched(self):
        state,api,_=prepared("shipping_address");original=deepcopy(state)
        for requests in ([],[request(),request()],[dict(request(),status="succeeded")]):
            with self.subTest(requests=requests),self.assertRaises(InvalidTaskPlan):present_task_plan(state,requests)
            self.assertEqual(state,original)

    def test_return_exchange_conflict_does_not_affect_another_orders_cancel(self):
        state,api=two_orders();api.orders["#TEST1"]["status"]="delivered"
        state=accept_read(state,api,"get_order",{"order_id":"#TEST1"},"delivered-one")
        _,state=present_task_plan(state,[request("return"),request("exchange"),request("cancel","#TEST3")])
        spec=specification("cancel");spec["target"]["order_id"]="#TEST3"
        _,state=present_proposals(state,[spec]);_,state=agree(state)
        self.assertEqual(assessment(state,"return")["code"],"same_order_return_exchange_conflict")
        self.assertEqual(assessment(state,"cancel","#TEST3")["code"],"preflight_candidate")

    def test_existing_backend_address_equal_to_proposal_is_not_completion(self):
        state,api,_=prepared("modify_items","shipping_address")
        self.assertEqual(api.orders["#TEST1"]["shipping_address"],specification()["parameters"])
        self.assertEqual(assessment(state,"modify_items")["code"],"dependency_result_required")
        self.assertEqual(assessment(state,"shipping_address")["code"],"preflight_candidate")

    def test_unplanned_proposal_cannot_become_a_task_candidate(self):
        state,api=verified_state();_,state=present_task_plan(state,[request("default_shipping_address")])
        _,state=present_proposals(state,[specification()]);_,state=agree(state)
        result=inspect_task_plan(state)
        self.assertEqual(result["details"]["preflight_candidates"],[])
        self.assertEqual(len(result["details"]["tasks"]),1)
        self.assertEqual(assessment(state,"default_shipping_address")["code"],"proposal_required")

    def test_task_diagnostics_are_owned_results_and_do_not_mutate_ledger(self):
        state,api,_=prepared("shipping_address");original=deepcopy(state)
        first=inspect_task_plan(state);second=inspect_task_plan(state)
        self.assertEqual(first,second)
        first["details"]["tasks"][0]["target"]["customer_id"]="forged"
        first["details"]["preflight_candidates"].clear()
        self.assertEqual(inspect_task_plan(state),second);self.assertEqual(state,original)

    def test_unconfirmed_prerequisite_does_not_block_other_order(self):
        state,api=two_orders()
        actions=[request("modify_items"),request(),request("shipping_address","#TEST3")]
        _,state=present_task_plan(state,actions)
        specs=[specification("modify_items"),specification(),specification()]
        specs[2]["target"]["order_id"]="#TEST3"
        _,state=present_proposals(state,specs);_,state=agree(state,"confirm operations 1 and 3")
        self.assertEqual(assessment(state,"modify_items")["code"],"dependency_result_required")
        self.assertEqual(assessment(state,"shipping_address")["code"],"scope_not_confirmed")
        self.assertEqual(assessment(state,"shipping_address","#TEST3")["code"],"preflight_candidate")

    def test_one_order_lock_does_not_block_other_order_or_default_record(self):
        state,api=two_orders()
        _,state=present_task_plan(state,[request("shipping_address"),request("shipping_address","#TEST3"),request("default_shipping_address")])
        specs=[specification(),specification(),specification("default_shipping_address")];specs[1]["target"]["order_id"]="#TEST3"
        _,state=present_proposals(state,specs);_,state=agree(state)
        api.orders["#TEST1"]["status"]="pending (items modified)"
        state=accept_read(state,api,"get_order",{"order_id":"#TEST1"},"lock-one")
        self.assertEqual(assessment(state,"shipping_address")["code"],"items_modified_lock")
        self.assertEqual(assessment(state,"shipping_address","#TEST3")["code"],"preflight_candidate")
        self.assertEqual(assessment(state,"default_shipping_address")["code"],"preflight_candidate")

    def test_cancel_conflict_is_preserved_even_if_only_cancel_is_confirmed(self):
        state,api=verified_state()
        _,state=present_task_plan(state,[request("cancel"),request("modify_items")])
        _,state=present_proposals(state,[specification("cancel")]);_,state=agree(state)
        for action in ("cancel","modify_items"):
            self.assertEqual(assessment(state,action)["code"],"same_order_cancel_conflict")
        self.assertEqual(inspect_task_plan(state)["details"]["preflight_candidates"],[])

    def test_conflict_choice_requires_new_plan_and_new_complete_proposal(self):
        state,api=verified_state(status="delivered")
        _,state=present_task_plan(state,[request("return"),request("exchange")])
        self.assertEqual(assessment(state,"return")["code"],"same_order_return_exchange_conflict")
        self.assertEqual(assessment(state,"exchange")["code"],"same_order_return_exchange_conflict")
        _,state=agree(state,"Choose exchange")
        _,state=present_task_plan(state,[request("exchange")])
        self.assertEqual(assessment(state,"exchange")["code"],"proposal_required")
        _,state=present_proposals(state,[specification("exchange")]);_,state=agree(state)
        self.assertEqual(assessment(state,"exchange")["code"],"preflight_candidate")
        self.assertEqual(len(state["tasks"]),1)

    def test_unpriced_return_can_be_planned_but_not_authorized(self):
        state,api=verified_state(status="delivered")
        _,state=present_task_plan(state,[request("return")])
        self.assertEqual(assessment(state,"return")["code"],"proposal_required")
        self.assertFalse(inspect_task_plan(state)["details"]["write_authorized"])
        self.assertEqual(state["proposals"],[])

    def test_withdrawal_and_conditions_propagate_specific_consent_diagnostics(self):
        for text,code in (("withdraw operation 1","proposal_withdrawn"),("yes if cheaper","condition_unresolved"),
                          ("change operation 1 to another address","proposal_amended")):
            state,api=verified_state();_,state=present_task_plan(state,[request()])
            _,state=present_proposals(state,[specification()]);_,state=agree(state,text)
            self.assertEqual(assessment(state,"shipping_address")["code"],code)
            self.assertFalse(assessment(state,"shipping_address")["details"]["write_authorized"])

    def test_changed_order_quote_invalidates_only_dependent_order_consent(self):
        state,api=two_orders();_,state=present_task_plan(state,[request("payment_method"),request("shipping_address","#TEST3")])
        specs=[specification("payment_method"),specification()];specs[1]["target"]["order_id"]="#TEST3"
        _,state=present_proposals(state,specs);_,state=agree(state)
        api.orders["#TEST1"]["items"][0]["price"]=13.5
        state=accept_read(state,api,"get_order",{"order_id":"#TEST1"},"price-one")
        self.assertEqual(assessment(state,"payment_method")["code"],"facts_changed")
        self.assertEqual(assessment(state,"shipping_address","#TEST3")["code"],"preflight_candidate")

    def test_missing_owned_order_facts_affect_only_that_task(self):
        state,api=verified_state(with_order=False)
        _,state=present_task_plan(state,[request(),request("default_shipping_address")])
        _,state=present_proposals(state,[specification("default_shipping_address")]);_,state=agree(state)
        self.assertEqual(assessment(state,"shipping_address")["code"],"task_facts_required")
        self.assertEqual(assessment(state,"default_shipping_address")["code"],"preflight_candidate")

    def test_failed_or_missing_refresh_blocks_only_affected_order(self):
        for outcomes_kind in ("failed","missing","wrong_id"):
            state,api=two_orders();_,state=present_task_plan(state,[request(),request("shipping_address","#TEST3")])
            specs=[specification(),specification()];specs[1]["target"]["order_id"]="#TEST3"
            _,state=present_proposals(state,specs);_,state=agree(state)
            call=ToolAction("bad-one","get_order",bind_arguments("get_order",{"order_id":"#TEST1"},state))
            record_decision(state,Decision(calls=(call,)))
            outcomes=(ToolOutcome(call.id,"private rejected body",error=True),) if outcomes_kind=="failed" else () if outcomes_kind=="missing" else (ToolOutcome("other","private rejected body"),)
            _,state=advance(TurnInput(kind="tools",outcomes=outcomes),state)
            self.assertEqual(assessment(state,"shipping_address")["code"],"order_read_unresolved")
            self.assertEqual(assessment(state,"shipping_address","#TEST3")["code"],"preflight_candidate")
            self.assertNotIn("private rejected body",json.dumps(state["history"]))
            restored=initial_state(state["history"])
            self.assertEqual(inspect_task_plan(restored),inspect_task_plan(state))

    def test_equal_successful_refresh_recovers_task_candidate(self):
        state,api,_=prepared("shipping_address")
        call=ToolAction("failed-refresh","get_order",bind_arguments("get_order",{"order_id":"#TEST1"},state));record_decision(state,Decision(calls=(call,)))
        _,state=advance(TurnInput(kind="tools",outcomes=()),state)
        self.assertEqual(assessment(state,"shipping_address")["code"],"order_read_unresolved")
        state=accept_read(state,api,"get_order",{"order_id":"#TEST1"},"restored-refresh")
        self.assertEqual(assessment(state,"shipping_address")["code"],"preflight_candidate")

    def test_pending_batch_and_handoff_block_frontier_without_dispatch(self):
        state,api,_=prepared("shipping_address")
        call=ToolAction("pending-refresh","get_order",bind_arguments("get_order",{"order_id":"#TEST1"},state));record_decision(state,Decision(calls=(call,)))
        self.assertEqual(inspect_task_plan(state)["code"],"pending_reads")
        _,state=advance(TurnInput(kind="tools",outcomes=()),state)
        state["handoff"]["status"]="accepted"
        self.assertEqual(inspect_task_plan(state)["code"],"invalid_state")  # Forged acceptance has no transfer journal.

    def test_plan_replacement_does_not_complete_or_rewrite_old_tasks_or_consent(self):
        state,api,_=prepared("modify_items","shipping_address");before=deepcopy(state)
        _,new=present_task_plan(state,[request("modify_items")])
        self.assertEqual(new["proposals"],before["proposals"])
        self.assertEqual(new["operations"],before["operations"])
        self.assertEqual(len(new["tasks"]),1)
        self.assertIn("No operation has been executed",new["history"][-1]["content"])
        self.assertEqual(state,before)

    def test_model_cannot_supply_task_plan_confirmation_or_progress(self):
        for candidate in ({"type":"task_plan","requests":[request()]},{"type":"tool","name":"plan_tasks","arguments":{}},
                          {"type":"reply","text":"done","task_status":"succeeded"}):
            with self.assertRaises(InvalidAction):decision_from_candidate(candidate,call_id="bad")
        state,api=verified_state();_,state=present_task_plan(state,[request()])
        _,state=agree(state,"yes")
        self.assertEqual(assessment(state,"shipping_address")["code"],"proposal_required")
        self.assertEqual(state["proposals"],[])

    def test_plan_rejects_foreign_customer_and_unowned_order_atomically(self):
        state,_=verified_state();before=deepcopy(state)
        foreign=request();foreign["target"]["customer_id"]="customer_b"
        for intents in ([foreign],[request("cancel","#TEST2")]):
            with self.assertRaisesRegex(InvalidTaskPlan,"verified customer's"):present_task_plan(state,intents)
        self.assertEqual(state,before)

    def test_new_other_order_only_set_supersedes_omitted_confirmed_task(self):
        state, _ = two_orders()
        _, state = present_task_plan(state, [request(), request("shipping_address", "#TEST3")])
        first = specification()
        second = specification(); second["target"]["order_id"] = "#TEST3"
        _, state = present_proposals(state, [first])
        _, state = agree(state)
        self.assertEqual(assessment(state, "shipping_address")["code"], "preflight_candidate")
        old_version = state["proposals"][-1]["version"]
        _, replaced = present_proposals(state, [second])
        self.assertEqual(assessment(replaced, "shipping_address")["code"], "proposal_required")
        self.assertEqual(assessment(replaced, "shipping_address", "#TEST3")["code"], "confirmation_required")
        old = next(p for p in replaced["proposals"] if p["version"] == old_version)
        self.assertEqual(old["status"], "superseded")
        self.assertIsNone(old["confirmation"])
        self.assertEqual(inspect_task_plan(initial_state(replaced["history"])), inspect_task_plan(replaced))

    def test_new_set_retains_reincluded_order_consent_while_other_order_changes(self):
        state, _ = two_orders()
        _, state = present_task_plan(state, [request(), request("shipping_address", "#TEST3")])
        first = specification()
        second = specification(); second["target"]["order_id"] = "#TEST3"
        _, state = present_proposals(state, [first, second])
        _, state = agree(state)
        original = next(p for p in state["proposals"] if p["spec"]["target"] == first["target"])
        evidence = deepcopy(original["confirmation"])
        changed = deepcopy(second); changed["parameters"]["city"] = "Another City"
        _, revised = present_proposals(state, [first, changed])
        self.assertEqual(assessment(revised, "shipping_address")["code"], "preflight_candidate")
        self.assertEqual(assessment(revised, "shipping_address", "#TEST3")["code"], "confirmation_required")
        current_first = next(p for p in revised["proposals"] if p["status"] == "confirmed" and p["spec"]["target"] == first["target"])
        self.assertEqual(current_first["reuse_version"], original["version"])
        self.assertEqual(current_first["confirmation"], evidence)
        self.assertTrue(confirmation_matches(revised, current_first["version"], first))
        self.assertEqual(revised["history"][evidence["history_index"]], state["history"][evidence["history_index"]])
        self.assertEqual(inspect_task_plan(initial_state(revised["history"])), inspect_task_plan(revised))

    def test_missing_user_index_is_a_controlled_error_if_scope_invariant_breaks(self):
        # Fault injection: a real verified prefix already requires user history.
        # Exercise the defensive branch if that upstream invariant changes.
        state = initial_state(); original = deepcopy(state)
        with patch("support_agent.tasks._request_scope", return_value=None):
            with self.assertRaisesRegex(InvalidTaskPlan, "preceding actual user request"):
                present_task_plan(state, [request()])
        self.assertEqual(state, original)

    def test_unverified_or_pending_plan_is_rejected_atomically(self):
        with self.assertRaisesRegex(InvalidTaskPlan,"verified idle"):present_task_plan(initial_state(),[request()])
        state,api=verified_state();call=ToolAction("pending-order","get_order",bind_arguments("get_order",{"order_id":"#TEST1"},state));record_decision(state,Decision(calls=(call,)))
        before=deepcopy(state)
        with self.assertRaisesRegex(InvalidTaskPlan,"verified idle"):present_task_plan(state,[request()])
        self.assertEqual(state,before)

    def test_inspection_reports_missing_plan_and_bad_state_structurally(self):
        self.assertEqual(inspect_task_plan(initial_state())["code"],"task_plan_required")
        bad=inspect_task_plan({})
        self.assertEqual(bad["decision"],"deny");self.assertEqual(bad["code"],"invalid_state")
        self.assertTrue(bad["details"]["state_error"]);self.assertFalse(bad["details"]["write_authorized"])


class TaskRecoveryTests(unittest.TestCase):
    def test_clone_and_history_recovery_keep_graph_and_diagnostics(self):
        state,_,_=prepared("modify_items","shipping_address");before=deepcopy(state)
        restored=initial_state(state["history"]);copied=clone_state(state)
        self.assertEqual(restored["tasks"],state["tasks"])
        self.assertEqual(restored["history"],state["history"])
        self.assertEqual(restored["identity_evidence"],state["identity_evidence"])
        self.assertEqual(copied,state);self.assertEqual(inspect_task_plan(restored),inspect_task_plan(state))
        self.assertEqual(state,before)

    def test_task_records_edges_targets_and_claimed_completion_cannot_be_forged(self):
        state,api,_=prepared("modify_items","shipping_address")
        for field,value in (("depends_on",[]),("request_index",True),("target",request("cancel","#TEST2")["target"]),
                            ("status","succeeded"),("id","arbitrary"),("action","cancel"),("plan_index",0),
                            ("conflicts",[{"task_id":"invented","code":"same_order_cancel_conflict"}])):
            damaged=deepcopy(state);damaged["tasks"][0][field]=value
            with self.subTest(field=field),self.assertRaises(InvalidState):clone_state(damaged)

    def test_plan_event_role_text_indices_and_mixed_metadata_are_rejected(self):
        state,api=verified_state();_,state=present_task_plan(state,[request()])
        for mutation in ("role","text","index","mixed"):
            damaged=deepcopy(state);entry=damaged["history"][-1]
            if mutation=="role":entry["role"]="user"
            elif mutation=="text":entry["content"]="All tasks completed"
            elif mutation=="index":entry["task_plan"]["request_index"]=True
            else:entry["proposal_set_ack"]=[]
            with self.subTest(mutation=mutation),self.assertRaises(InvalidState):clone_state(damaged)

    def test_future_identity_cannot_authorize_past_plan(self):
        state,api=verified_state();_,state=present_task_plan(state,[request()])
        history=deepcopy(state["history"]);event=history.pop()
        history.insert(0,event)
        with self.assertRaises((InvalidTaskPlan,InvalidState)):initial_state(history)

    def test_schema_one_two_three_cannot_smuggle_task_evidence(self):
        state,api=verified_state();_,state=present_task_plan(state,[request()])
        for version in (1,2,3,True,SCHEMA_VERSION+1):
            damaged=deepcopy(state);damaged["schema_version"]=version
            with self.subTest(version=version),self.assertRaises(InvalidState):clone_state(damaged)

    def test_fixed_schema_three_fixture_preserves_original_partial_consent(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/m3_schema3_state.json').read_text(encoding='utf-8'))
        state=fixture["state"];before=deepcopy(state)
        self.assertEqual(fixture["source_commit"],"3460329e24c69e6c7648c2702a5c834347ac05e4")
        self.assertEqual(state["schema_version"],3);self.assertEqual(state["tasks"],[])
        migrated=clone_state(state)
        self.assertEqual(migrated["schema_version"],SCHEMA_VERSION)
        self.assertEqual(migrated["history"],state["history"]);self.assertEqual(migrated["proposals"],state["proposals"])
        self.assertTrue(confirmation_matches(migrated,1,specification()))
        self.assertFalse(confirmation_matches(migrated,2,specification("payment_method")))
        self.assertEqual(state,before)

    def test_legacy_nonempty_untraced_tasks_and_missing_tasks_key_are_rejected(self):
        state=initial_state()
        for version in (1,2,3):
            for tasks in (None,[request()]):
                damaged=deepcopy(state);damaged["schema_version"]=version
                if tasks is None:del damaged["tasks"]
                else:damaged["tasks"]=tasks
                with self.subTest(version=version,tasks=tasks),self.assertRaises(InvalidState):clone_state(damaged)

    def test_plain_assistant_text_cannot_reconstruct_plan_or_completion(self):
        state,api=verified_state();decision,planned=present_task_plan(state,[request()])
        history=deepcopy(planned["history"]);del history[-1]["task_plan"]
        restored=initial_state(history)
        self.assertEqual(restored["tasks"],[]);self.assertEqual(inspect_task_plan(restored)["code"],"task_plan_required")
        self.assertEqual(restored["proposals"],[])


if __name__=='__main__':unittest.main()
