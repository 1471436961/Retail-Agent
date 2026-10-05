"""Cancellation producer; original user sources, common consent and journal."""
import re
from copy import deepcopy

from support_agent.address_session import _accepted_bodies, _safe_read
from support_agent.domain.cancellation_intake import request_from_history, refund_recap_rule
from support_agent.domain.orders import order_state_rule
from support_agent.domain.policies import cancellation_reason_rule
from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES, WorkflowResultTooLarge, json_bytes
from support_agent.workflow_boundary import WorkflowBoundary, unfinished_other_tasks
from support_agent.protocol import InvalidAction
from support_agent.state import clone_state


def _boundary():
    return WorkflowBoundary("cancellation", MAX_WORKFLOW_RESULT_BYTES)


def restore_cancellation_control(state, index):
    return _boundary().restore(state, index)


def accept_cancellation_result(state, outcomes):
    return _boundary().accept(state, outcomes)


def route_cancellation(state, text=None):
    from support_agent.proposals import _current_records
    if state["cancellation_pending"] is not None:
        return _boundary().reply(state, "cancellation_workflow_unresolved", "The cancellation workflow result is unresolved. I will not repeat it or claim a completed cancellation/refund.")
    request = request_from_history(state["history"])
    if request is None:
        return None
    from support_agent.domain.addresses import request_from_history as address_request
    from support_agent.domain.payment_intake import request_from_history as payment_request
    if any(other and other["request_index"] > request["request_index"]
           for other in (address_request(state["history"]), payment_request(state["history"]))):
        return None
    if request["error"] == "mixed_business_request":
        return _boundary().reply(state, "mixed_business_request", "Cancellation conflicts with other changes on the same order. Choose a final operation in a separate workflow; no business request was submitted.")
    from support_agent.adapters.read_api import customer_order_ids
    if request["order_id"] and not request["error"] and request["order_id"] not in customer_order_ids(state["customer_record"]):
        return _boundary().reply(state, "cancellation_order_not_owned", "This order is outside your accepted verified references. I cannot dispatch its cancellation; clarify your own order or refresh your profile first.", decision_kind="deny")
    latest = max(i for i,e in enumerate(state["history"]) if e["role"] == "user")
    attempted = {o["version"] for o in state["operations"] if o["mutates"]}
    confirmed = [p for p in _current_records(state) if p["spec"]["action"] == "cancel" and p["status"] == "confirmed" and p["version"] not in attempted]
    if text is not None and re.search(r"\b(retry|try again)\b|重试|重新准备", text, re.I):
        return _boundary().dispatch(state, "prepare")
    changed = request["request_index"] == latest
    if confirmed and not changed and any(p["confirmation"] and p["confirmation"]["history_index"] == latest for p in confirmed):
        return _boundary().dispatch(state, "execute")
    if text is None or changed:
        return _boundary().dispatch(state, "prepare")
    return None


def _prepare(state, api, notice=""):
    from support_agent.adapters.read_api import customer_order_ids
    from support_agent.proposals import _current_records, normalize_spec, present_proposals
    from support_agent.tasks import present_task_plan
    boundary = _boundary()
    request = request_from_history(state["history"])
    if request is None or request["error"]:
        code = request["error"] if request else "cancellation_request_required"
        messages = {"target_order_required":"Please provide the exact owned order ID to cancel.",
                    "single_order_required":"Please choose one exact order for this complete cancellation proposal.",
                    "full_original_refunds_required":"Cancellation refunds every charge in full; partial refunds or withholding are unsupported. Please clarify a new cancellation request.",
                    "conditional_cancellation_request":"The condition is unresolved. Please give a new explicit cancellation request; conditional assent is not permission.",
                    "cancellation_original_destination_required":"Cancellation refunds each charge only to its original payment method. A different destination is unsupported; clarify with a new cancellation request.",
                    "mixed_business_request":"Cancellation conflicts with other changes on the same order. Please choose the final operation; no request was submitted."}
        return boundary.reply(state, code, messages.get(code,"Please clarify the cancellation request; no business write was sent."),
                              decision_kind="deny" if code in {"cancellation_original_destination_required", "full_original_refunds_required"} else "needs_information")
    if state["tool_calls_since_user"] + 2 > 12:
        return boundary.reply(state,"cancellation_read_budget_exceeded","The complete profile/order refresh exceeds this request's budget; no cancellation was sent.")
    _, status = _safe_read(state, api, "read_customer_profile", {})
    if status != "succeeded":
        return boundary.reply(state,"cancellation_profile_read_failed","Profile refresh failed; old facts do not replace this read.")
    if request["order_id"] not in customer_order_ids(state["customer_record"]):
        return boundary.reply(state,"cancellation_order_not_owned","This order is outside your verified references; no order read or cancellation was requested.",decision_kind="deny")
    _, status = _safe_read(state, api, "get_order", {"order_id":request["order_id"]})
    if status != "succeeded":
        return boundary.reply(state,"cancellation_order_read_failed","The owned order refresh failed; old order facts do not replace it.")
    order = _accepted_bodies(state["history"], {"get_order"})[-1]
    target = {"customer_id":state["identity"]["customer_id"],"order_id":request["order_id"]}
    record = {"action":"cancel","target":target}
    def answer(result):
        return boundary.reply(state,result["code"],(notice+"\n" if notice else "")+result["message"],decision_kind=result["decision"],
                              records=[{**record,"decision":result["decision"],"code":result["code"]}],**result.get("details",{}))
    guard = order_state_rule(order,"cancel")
    if guard["decision"] != "allow": return answer(guard)
    if any(o["mutates"] and o["spec"]["target"] == target and (o["status"] in {"sent","unknown","acknowledged"} or o["persistence_unresolved"]) for o in state["operations"]):
        return boundary.reply(state,"write_result_unresolved","An earlier operation on this order remains unresolved; no new cancellation may be submitted.")
    reason = cancellation_reason_rule(request["reason"])
    if reason["decision"] != "allow":
        reason["message"] += " Allowed reasons: no longer needed or ordered by mistake, including clear natural synonyms. Other reasons require clarification or human assistance; no cancellation was sent."
        return answer(reason)
    quote = refund_recap_rule(order["payments"],state["customer_record"]["payment_methods"])
    if quote["decision"] != "allow": return answer(quote)
    attempted = {o["version"] for o in state["operations"] if o["mutates"]}
    if any(p["spec"]["action"] != "cancel" and p["version"] not in attempted for p in _current_records(state)) or unfinished_other_tasks(state,{"cancel"}):
        return boundary.reply(state,"cancellation_mixed_plan_requires_review","An unfinished non-cancellation proposal needs a final choice. It was not silently discarded.")
    spec = normalize_spec({"action":"cancel","target":target,"parameters":{"reason":reason["details"]["reason"]},
                           "amount":{"kind":"per_charge_refunds","rows":quote["details"]["charges"]}})
    notes = [notice] if notice else []
    notes += [f'Current order status: {order["status"]}.',
              f'Original charge total (sum of recorded amounts, not a net balance): {quote["details"]["display_total"]}.',
              "Each charge will be refunded separately in full to its own original method; no fees, withheld portion, new card or separate refund API."]
    notes += [f'Charge {row["charge_index"]}: {row["display_amount"]} to {row["destination_label"]}; channel policy: {row["timing"]}.' for row in quote["details"]["rows"]]
    notes += ["Cancellation should record cancelled and the per-charge refunds. Channel timing is policy, not proof of settlement or arrival."]
    _, state = present_task_plan(state,[{"action":"cancel","target":target}])
    decision,state = present_proposals(state,[spec],presentation_note="\n".join(notes))
    return boundary.tag(decision,state,"cancellation_confirmation_required",records=[{**record,"decision":"needs_information","code":"cancellation_recapped"}])


def run_cancellation_workflow(state, api, claims):
    from support_agent.proposals import _current_records
    from support_agent.adapters.write_runtime import SessionWriteRuntime
    from support_agent.write_session import execute_operation
    state=clone_state(state); original=deepcopy(state); pending=state["cancellation_pending"]; boundary=_boundary()
    if (pending is None or pending["status"] != "pending" or len(state["history"]) != pending["index"]+1
            or not state["identity"]["verified"] or not state["identity_evidence"] or state["pending_calls"] or state["items_pending"] is not None
            or any(state[k+"_pending"] is not None for k in ("address","payment")) or state["handoff"]["status"] not in {"not_requested", "rejected"}):
        raise ValueError("An original idle verified cancellation dispatch is required")
    if pending["mode"] == "prepare":
        boundary.event(state,"cancellation_result",{"call_id":pending["call_id"]})
        try: decision,state=_prepare(state,api)
        except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
            state=deepcopy(original); boundary.event(state,"cancellation_result",{"call_id":pending["call_id"]})
            decision,state=boundary.reply(state,"cancellation_preparation_failed","Cancellation preparation failed. No business write was sent; clarify or retry preparation.")
    else:
        attempted={o["version"] for o in state["operations"] if o["mutates"]}
        selected=[p for p in _current_records(state) if p["status"]=="confirmed" and p["version"] not in attempted]
        if len(selected)!=1 or selected[0]["spec"]["action"]!="cancel":
            raise ValueError("One confirmed complete cancellation proposal is required")
        proposal=selected[0]; spec=deepcopy(proposal["spec"])
        try: runtime=SessionWriteRuntime(api,claims=claims)
        except (TypeError,ValueError,RuntimeError):
            boundary.event(state,"cancellation_result",{"call_id":pending["call_id"]})
            decision,state=boundary.reply(state,"cancellation_runtime_unavailable","Trusted cancellation runtime is unavailable; no write was sent.")
            return _payload(decision,state,original,pending)
        uncertain=False
        try: result,state=execute_operation(state,proposal["version"],spec,runtime)
        except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
            uncertain=True; result={"decision":"needs_information","code":"cancellation_operation_uncertain"}
        boundary.event(state,"cancellation_unknown" if uncertain else "cancellation_result",{"call_id":pending["call_id"]})
        records=[{"action":"cancel","target":spec["target"],"version":proposal["version"],"decision":result["decision"],"code":result["code"]}]
        if result["code"] in {"facts_changed", "facts_unavailable"}:
            try: decision,state=_prepare(state,api,"Accepted cancellation facts changed or no longer support the old proposal. No old-version write was sent; review and confirm a new complete proposal.")
            except (InvalidAction,TypeError,ValueError,KeyError,OverflowError,RuntimeError):
                decision,state=boundary.reply(state,"cancellation_repreparation_failed","Facts changed; new cancellation preparation failed. No additional write was sent.",records=records)
        else:
            if result["code"]=="write_verified":
                quote=refund_recap_rule(spec["amount"]["rows"],state["customer_record"]["payment_methods"])
                timings="; ".join(f'{r["payment_method_id"]}: {r["timing"]}' for r in quote["details"]["rows"])
                text=f'Order {spec["target"]["order_id"]}: cancellation accepted and independently verified: cancelled, with each full refund record to its original method. Channel policy: {timings}. These records do not prove settlement or arrival; no separate refund or retry was requested.'
            elif result["code"]=="write_rejected":
                text="Cancellation was rejected. No automatic retry or separate refund was requested; a new explicit request requires a fresh full proposal and confirmation."
            else:
                text="Cancellation is not verified ("+result["code"]+"). I will not repeat an uncertain operation or claim cancellation/refund completion."
            decision,state=boundary.reply(state,"cancellation_execution_uncertain" if uncertain else result["code"],text,records=records,
                                          decision_kind="allow" if result["code"]=="write_verified" else "needs_information")
    return _payload(decision,state,original,pending)


def _payload(decision,state,original,pending):
    payload={"reply":decision.text,"state":clone_state(state),"assessment":state["history"][-1]["cancellation_assessment"]}
    if json_bytes(payload)<=MAX_WORKFLOW_RESULT_BYTES: return payload
    if pending["mode"]=="prepare":
        state=deepcopy(original); _boundary().event(state,"cancellation_result",{"call_id":pending["call_id"]})
        decision,state=_boundary().reply(state,"cancellation_result_budget_exceeded","The read-only cancellation result exceeds the budget. Original evidence is preserved; no write was sent.")
        payload={"reply":decision.text,"state":clone_state(state),"assessment":state["history"][-1]["cancellation_assessment"]}
        if json_bytes(payload)<=MAX_WORKFLOW_RESULT_BYTES: return payload
    raise WorkflowResultTooLarge("Cancellation outcome delivery exceeds the budget; never a rejected business write")
