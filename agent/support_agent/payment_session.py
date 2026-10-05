"""M4.2 payment producer; shared consent, claims and workflow transport."""
import re
from copy import deepcopy

from support_agent.workflow_limits import WorkflowResultTooLarge, MAX_WORKFLOW_RESULT_BYTES, json_bytes
from support_agent.address_session import _accepted_bodies, _safe_read
from support_agent.domain.payment_intake import request_from_history, starts_payment_request, current_charge_rule, resolve_choice, method_label
from support_agent.domain.addresses import starts_address_request
from support_agent.domain.policies import _methods, refund_timing_rule
from support_agent.domain.orders import order_state_rule
from support_agent.workflow_boundary import WorkflowBoundary, unfinished_other_tasks
from support_agent.protocol import InvalidAction
from support_agent.state import clone_state

def _boundary():
    return WorkflowBoundary("payment", MAX_WORKFLOW_RESULT_BYTES)


def restore_payment_control(state, index):
    return _boundary().restore(state, index)


def accept_payment_result(state, outcomes):
    return _boundary().accept(state, outcomes)


def route_payment(state, text=None):
    from support_agent.proposals import _current_records
    if state["payment_pending"] is not None:
        return _boundary().reply(state, "payment_workflow_unresolved", "The payment workflow result remains unresolved. I will not repeat it or claim completion.")
    if text is not None and starts_address_request(text):
        return None
    from support_agent.domain.cancellation_intake import starts_cancellation_request
    if text is not None and starts_cancellation_request(text):
        return None
    request = request_from_history(state["history"])
    if request is None:
        return None
    from support_agent.domain.addresses import request_from_history as address_request
    address = address_request(state["history"])
    if address is not None and address["request_index"] > request["request_index"]:
        return None
    from support_agent.domain.cancellation_intake import request_from_history as cancellation_request
    cancellation = cancellation_request(state["history"])
    if cancellation is not None and cancellation["request_index"] > request["request_index"]:
        return None
    current = _current_records(state)
    latest_index = max(i for i,e in enumerate(state["history"]) if e["role"] == "user")
    attempted = {o["version"] for o in state["operations"] if o["mutates"]}
    confirmed = [p for p in current if p["spec"]["action"] == "payment_method" and p["status"] == "confirmed" and p["version"] not in attempted]
    # A new/corrected selection is re-prepared even if a previous scope retained
    # consent. No user text edits a specification or creates a write directly.
    if text is not None and re.search(r"\b(retry|try again)\b|重试|重新准备", text, re.I):
        return _boundary().dispatch(state, "prepare")
    changed_request = request["request_index"] == latest_index
    fresh_assent = any(p["confirmation"] and p["confirmation"]["history_index"] == latest_index for p in confirmed)
    if confirmed and fresh_assent and not changed_request:
        return _boundary().dispatch(state, "execute")
    if text is None or changed_request:
        return _boundary().dispatch(state, "prepare")
    return None


def _prepare(state, api, notice=""):
    from support_agent.adapters.read_api import customer_order_ids
    from support_agent.proposals import _current_records, normalize_spec, present_proposals
    from support_agent.tasks import present_task_plan
    boundary = _boundary()
    request = request_from_history(state["history"])
    if request is None or request["error"]:
        code = request["error"] if request else "payment_request_required"
        messages = {"target_order_required":"Please provide the exact owned order ID for the payment change.",
                    "single_order_required":"Please choose one exact order for this complete payment proposal.",
                    "single_method_required":"Split or partial payment is unsupported. Choose one saved method covering the whole order.",
                    "conditional_payment_request":"Please clarify the condition with a new explicit request. Conditional assent does not authorize a payment change."}
        return boundary.reply(state, code, messages.get(code, "Please clarify the payment request and select one saved method; no change was sent."), decision_kind="deny" if code == "single_method_required" else "needs_information")
    if state["tool_calls_since_user"] + 2 > 12:
        return boundary.reply(state, "payment_read_budget_exceeded", "The complete profile and order refresh exceeds this request's read budget; no change was sent.")
    _, status = _safe_read(state, api, "read_customer_profile", {})
    if status != "succeeded":
        return boundary.reply(state, "payment_profile_read_failed", "The profile refresh failed; old saved-method facts will not replace it.")
    order_id = request["order_id"]
    if order_id not in customer_order_ids(state["customer_record"]):
        return boundary.reply(state, "payment_order_not_owned", "This order is outside your verified references; no order details or write were requested.", decision_kind="deny")
    _, status = _safe_read(state, api, "get_order", {"order_id":order_id})
    if status != "succeeded":
        return boundary.reply(state, "payment_order_read_failed", "The owned order could not be refreshed; no earlier order body can replace this read.")
    order = _accepted_bodies(state["history"], {"get_order"})[-1]
    target = {"customer_id":state["identity"]["customer_id"], "order_id":order_id}
    record = {"action":"payment_method", "target":target}
    def answer(result):
        return boundary.reply(state, result["code"], (notice + "\n" if notice else "") + result["message"], decision_kind=result["decision"], records=[{**record,"decision":result["decision"],"code":result["code"]}], **result.get("details", {}))
    guard = order_state_rule(order, "payment_method")
    if guard["decision"] != "allow": return answer(guard)
    if any(o["mutates"] and o["spec"]["target"] == target and (o["status"] in {"sent","unknown","acknowledged"} or o["persistence_unresolved"]) for o in state["operations"]):
        return boundary.reply(state, "write_result_unresolved", "An earlier operation on this record remains unresolved; a matching current method does not prove success.")
    methods = state["customer_record"]["payment_methods"]
    basis = current_charge_rule(order["payments"], methods)
    if basis["decision"] != "allow": return answer(basis)
    charge = basis["details"]["charge"]
    choice = resolve_choice(methods, request["selection"], charge)
    if choice["decision"] != "allow":
        choice["message"] += " Saved methods: " + "; ".join(method_label(m) for m in methods)
        return answer(choice)
    attempted = {o["version"] for o in state["operations"] if o["mutates"]}
    current = _current_records(state)
    if any(p["spec"]["action"] != "payment_method" and p["version"] not in attempted for p in current) or unfinished_other_tasks(state, {"payment_method"}):
        return boundary.reply(state, "payment_mixed_plan_requires_review", "An unfinished non-payment proposal needs clarification; it has not been silently discarded.")
    selected = choice["details"]["payment_method_id"]
    saved = _methods(methods)
    spec = normalize_spec({"action":"payment_method", "target":target, "parameters":{"payment_method_id":selected}, "amount":{"kind":"order_total", "value":charge["amount"], "refund_rows":[charge]}})
    timing = refund_timing_rule(saved[charge["payment_method_id"]]["source"])["details"]["timing"]
    note = ((notice + "\n") if notice else "") + ("The requested gift card is insufficient; the customer's specified fallback was selected.\n" if choice["details"].get("fallback_used") else "")
    note += (f'Original method: {method_label(saved[charge["payment_method_id"]])}.\n'
             f'New method: {method_label(saved[selected])}.\n'
             f'Payment-switch policy requires the full new charge of {charge["amount"]} to succeed before the full original amount is refunded to the original method.\n'
             'We will submit one payment-method change and verify its returned records; transaction-list order does not establish actual processing order.\n'
             f'Refund channel policy: {timing}; this is not proof of settlement or arrival. Order remains pending after a successful switch.')
    _, state = present_task_plan(state, [{"action":"payment_method", "target":target}])
    decision, state = present_proposals(state, [spec], presentation_note=note)
    return boundary.tag(decision, state, "payment_confirmation_required", records=[{**record,"decision":"needs_information","code":"payment_recapped"}])


def run_payment_workflow(state, api, claims):
    from support_agent.proposals import _current_records
    from support_agent.adapters.write_runtime import SessionWriteRuntime
    from support_agent.write_session import execute_operation
    state = clone_state(state); original = deepcopy(state); pending = state["payment_pending"]
    boundary = _boundary()
    if (pending is None or pending["status"] != "pending" or len(state["history"]) != pending["index"] + 1
            or not state["identity"]["verified"] or not state["identity_evidence"] or state["pending_calls"]
            or state["cancellation_pending"] is not None or state["address_pending"] is not None or state["items_pending"] is not None or state["handoff"]["status"] not in {"not_requested", "rejected"}):
        raise ValueError("An original idle verified payment dispatch is required")
    if pending["mode"] == "prepare":
        boundary.event(state, "payment_result", {"call_id":pending["call_id"]})
        try: decision, state = _prepare(state, api)
        except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
            state = deepcopy(original); boundary.event(state, "payment_result", {"call_id":pending["call_id"]})
            decision, state = boundary.reply(state, "payment_preparation_failed", "Payment preparation could not complete. No business write was sent; clarify or retry preparation.")
    else:
        attempted = {o["version"] for o in state["operations"] if o["mutates"]}
        selected = [p for p in _current_records(state) if p["status"] == "confirmed" and p["version"] not in attempted]
        if len(selected) != 1 or selected[0]["spec"]["action"] != "payment_method":
            raise ValueError("One confirmed complete payment proposal is required")
        proposal = selected[0]; spec = deepcopy(proposal["spec"])
        try: runtime = SessionWriteRuntime(api, claims=claims)
        except (TypeError, ValueError, RuntimeError):
            boundary.event(state, "payment_result", {"call_id":pending["call_id"]})
            decision, state = boundary.reply(state, "payment_runtime_unavailable", "The trusted payment runtime is unavailable; no change was sent.")
            return _payload(decision, state, original, pending)
        uncertain = False
        try: result, state = execute_operation(state, proposal["version"], spec, runtime)
        except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
            uncertain = True
            result = {"decision":"needs_information", "code":"payment_operation_uncertain"}
        boundary.event(state, "payment_unknown" if uncertain else "payment_result", {"call_id":pending["call_id"]})
        records = [{"action":"payment_method", "target":spec["target"], "version":proposal["version"], "decision":result["decision"], "code":result["code"]}]
        if result["code"] == "facts_changed":
            try: decision, state = _prepare(state, api, "The accepted payment facts changed; no old-version write was sent. A new full proposal requires fresh confirmation.")
            except (InvalidAction, TypeError, ValueError, KeyError, OverflowError, RuntimeError):
                decision, state = boundary.reply(state, "payment_repreparation_failed", "Facts changed and a new payment proposal could not be prepared. No additional write was sent.", records=records)
        else:
            if result["code"] == "write_verified":
                source = _methods(state["customer_record"]["payment_methods"])[spec["amount"]["refund_rows"][0]["payment_method_id"]]["source"]
                timing = refund_timing_rule(source)["details"]["timing"]
                text = f'Order {spec["target"]["order_id"]}: the payment switch is accepted and independently verified, including the full new charge and original refund records. Order remains pending. Refund channel policy: {timing}; these records do not independently prove processing order, settlement or arrival.'
            elif result["code"] == "write_rejected":
                text = "The payment switch was rejected. No automatic retry or separate refund was requested; you may choose another saved method and review a new full proposal."
            else:
                text = "The payment switch is not verified (" + result["code"] + "). I will not repeat an uncertain operation or claim a completed switch/refund."
            decision, state = boundary.reply(state, "payment_execution_uncertain" if uncertain else result["code"], text, records=records, decision_kind="allow" if result["code"] == "write_verified" else "needs_information")
    return _payload(decision, state, original, pending)


def _payload(decision, state, original, pending):
    payload = {"reply":decision.text,"state":clone_state(state),"assessment":state["history"][-1]["payment_assessment"]}
    if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES: return payload
    if pending["mode"] == "prepare":
        state = deepcopy(original); _boundary().event(state,"payment_result",{"call_id":pending["call_id"]})
        decision, state = _boundary().reply(state,"payment_result_budget_exceeded","The read-only payment result exceeds the tool budget. Original identity, consent and journal were preserved; no business write was sent.")
        payload = {"reply":decision.text,"state":clone_state(state),"assessment":state["history"][-1]["payment_assessment"]}
        if json_bytes(payload) <= MAX_WORKFLOW_RESULT_BYTES: return payload
    raise WorkflowResultTooLarge("Payment outcome delivery exceeds the internal budget; never a rejected business write")
