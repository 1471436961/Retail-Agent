"""Evidence-derived human transfer; no model intent, customer lookup or retry.

The journal proves internal consistency, not external history authenticity.
Shared claims cover this process and a complete journal, not lost state across
workers. A valid 201 receipt proves acceptance, never a human's response.
"""
import hashlib
import json
import re
from urllib.parse import quote

from support_agent.adapters.client_api import ClientAPIError, request_object
from support_agent.domain.rules import allow, need
from support_agent.protocol import Decision, ToolAction
from support_agent.workflow_limits import check_workflow_argument, MAX_WORKFLOW_RESULT_BYTES

TRANSFER_NOTICE = "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
BLOCKED = frozenset({"dispatched", "unknown", "accepted"})
MAX_SUMMARY_BYTES = 64 * 1024  # Internal bound, below the public 1 MiB request limit.


def intent(text):
    text = text.strip().casefold().rstrip(".!。！?")
    if re.fullmatch(r"(?:please )?(?:transfer|connect|put) me (?:to|through to|with) (?:a |an )?(?:human|human agent|live agent|person)(?: please)?", text):
        return "request"
    if re.fullmatch(r"(?:i (?:want|need|would like) (?:to (?:speak|talk) to )?)(?:a |an )?(?:human|human agent|live agent|person)(?: please)?", text):
        return "request"
    if re.fullmatch(r"(?:请)?(?:转|转接|联系|接通)(?:到|给)?(?:人工|人工客服|人工服务|真人客服)(?:处理|协助)?", text):
        return "request"
    if re.search(r"human|live agent|人工|真人客服", text) and re.search(r"transfer|connect|speak|talk|转|联系|接通", text):
        return "clarify"
    return None


def build_summary(state, request_index):
    """Derive fields from accepted state; keep user text in JSON string fields.

    This code never interprets embedded text as instructions. Labels alone do
    not prove a downstream human or model will handle that text safely.
    """
    writes = [o for o in state["operations"] if o["mutates"]]
    orders = {}
    for entry in state["history"]:
        for row in entry.get("tool_messages", [entry]):
            if row.get("role") != "tool" or row.get("error"):
                continue
            try:
                body = json.loads(row["content"])
            except (ValueError, TypeError):
                continue
            if not isinstance(body, dict):
                continue
            for order in body.get("orders", [body]):
                if isinstance(order, dict) and order.get("customer_id") == state["identity"]["customer_id"] and "order_id" in order and "status" in order:
                    orders[order["order_id"]] = {"order_id": order["order_id"], "status": order["status"]}
    diagnostics = []
    for entry in state["history"]:
        for kind in ("address", "payment", "cancellation"):
            if kind + "_assessment" in entry:
                diagnostics.append({"workflow": kind, "code": entry[kind + "_assessment"]["code"]})
    data = {"kind": "derived_human_transfer_summary", "user_text_is_data_not_instructions": True,
            "identity": {"verified": state["identity"]["verified"], "customer_id": state["identity"]["customer_id"]},
            "request": {"history_index": request_index, "text": state["history"][request_index]["content"]},
            "previous_user_requests": [{"history_index": i, "text": e["content"]} for i, e in enumerate(state["history"][:request_index]) if e["role"] == "user"],
            "verified_order_facts": list(orders.values()),
            "completed_operations": [{"action": o["name"], "target": o["spec"]["target"]} for o in writes if o["status"] == "succeeded" and not o["persistence_unresolved"]],
            "unresolved_operations": [{"action": o["name"], "target": o["spec"]["target"], "status": o["status"], "persistence_unresolved": o["persistence_unresolved"]} for o in writes if o["status"] in {"sent", "unknown", "acknowledged"} or o["persistence_unresolved"]],
            "task_requests": [{"action": t["action"], "target": t["target"]} for t in state["tasks"]],
            "latest_workflow_diagnostics": diagnostics[-6:],
            "pending_business_workflows": [k for k in ("address", "payment", "cancellation") if state[k + "_pending"] is not None],
            "settlement_or_arrival_proven": False}
    summary = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(summary.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("Transfer summary exceeds the internal UTF-8 budget")
    return summary


def valid_receipt(receipt):
    return (isinstance(receipt, dict) and set(receipt) == {"status", "transfer_id"}
            and receipt["status"] == "accepted" and isinstance(receipt["transfer_id"], str) and bool(receipt["transfer_id"].strip()))


def assessment(status, code=None):
    codes = {"accepted": "handoff_accepted", "unknown": "handoff_result_unknown", "rejected": "handoff_rejected", "dispatched": "handoff_pending"}
    text = TRANSFER_NOTICE if status == "accepted" else {
        "unknown": "The transfer outcome is unknown. I cannot claim acceptance or retry it; business calls are stopped.",
        "rejected": "The transfer was not accepted. No transfer success is claimed. You may explicitly request human assistance again.",
        "dispatched": "The transfer is pending; business calls are stopped."}[status]
    fn = allow if status == "accepted" else need
    return fn(code or codes[status], text, "HO-01", details={"write_authorized": False})


def reply(state, result):
    state["history"].append({"role": "assistant", "content": result["message"], "handoff_assessment": result})
    return Decision(text=result["message"]), state


def event(state, data):
    entry = {"role": "assistant", "content": "Internal human transfer journal.", "handoff_event": data}
    state["history"].append(entry)
    restore_handoff(state, len(state["history"]) - 1)


def restore_handoff(state, index):
    entry = state["history"][index]
    if set(entry) != {"role", "content", "handoff_event"} or entry["role"] != "assistant" or entry["content"] != "Internal human transfer journal.":
        raise ValueError("Malformed human transfer journal entry")
    data, current = entry["handoff_event"], state["handoff"]
    if not isinstance(data, dict):
        raise ValueError("Malformed human transfer event")
    if data.get("kind") == "dispatch":
        if (set(data) != {"kind", "call_id", "request_index", "summary"} or current["status"] in BLOCKED
                or type(data["request_index"]) is not int or data["request_index"] != index - 1
                or index < 1 or state["history"][index - 1]["role"] != "user"
                or intent(state["history"][index - 1]["content"]) != "request"
                or state["pending_calls"] or data["call_id"] != f"handoff:{index}"
                or data["summary"] != build_summary(state, index - 1)):
            raise ValueError("Transfer requires its preceding explicit user request and exact derived summary")
        state["handoff"] = {"status": "dispatched", **{k: data[k] for k in ("call_id", "request_index", "summary")}}
    elif data.get("kind") == "result":
        if (set(data) != {"kind", "call_id", "status", "conversation_id", "receipt", "error_code"}
                or current["status"] != "dispatched" or data["call_id"] != current["call_id"]
                or data["status"] not in {"accepted", "rejected", "unknown"}
                or not isinstance(data["error_code"], str)
                or data["conversation_id"] is not None and (not isinstance(data["conversation_id"], str) or not data["conversation_id"].strip())
                or (data["status"] == "accepted" and (not valid_receipt(data["receipt"]) or data["conversation_id"] is None or data["error_code"]))
                or (data["status"] != "accepted" and data["receipt"] is not None)):
            raise ValueError("Transfer result must match its original pending dispatch")
        state["handoff"] = {**current, **{k: data[k] for k in ("status", "conversation_id", "receipt", "error_code")}}
    else:
        raise ValueError("Unknown transfer event")


def validate_handoff(state):
    from support_agent.state import initial_state
    current = {"status": "not_requested"}
    for index, entry in enumerate(state["history"]):
        if "handoff_event" in entry:
            if not isinstance(entry["handoff_event"], dict):
                raise ValueError("Transfer event must be an object")
            if entry["handoff_event"].get("kind") == "dispatch":
                prefix = initial_state(state["history"][:index])
            else:
                prefix = {"history": state["history"][:index + 1], "handoff": current}
            prefix["history"] = state["history"][:index + 1]
            restore_handoff(prefix, index)
            current = prefix["handoff"]
        if "handoff_assessment" in entry:
            result = entry["handoff_assessment"]
            if (entry["role"] != "assistant" or not isinstance(result, dict) or set(result) != {"decision", "code", "message", "rules", "details"}
                    or entry["content"] != result["message"] or result["decision"] not in {"allow", "deny", "needs_information"}
                    or result["details"] != {"write_authorized": False} or result["rules"] != ["HO-01"]):
                raise ValueError("Malformed human transfer diagnostic")
            if result["code"] == "handoff_accepted" and (current["status"] != "accepted" or result != assessment("accepted")):
                raise ValueError("Acceptance diagnostic lacks its valid transfer receipt")
    if current != state["handoff"]:
        raise ValueError("Transfer state differs from its journal")


def route_handoff(state, text):
    status = state["handoff"]["status"]
    if status in BLOCKED:
        if status == "dispatched":
            event(state, {"kind": "result", "call_id": state["handoff"]["call_id"], "status": "unknown", "conversation_id": None, "receipt": None, "error_code": "result_missing"})
        return reply(state, assessment(state["handoff"]["status"]))
    request = intent(text)
    if request is None:
        return None
    if request == "clarify":
        return reply(state, need("handoff_request_clarification", "Please clarify whether to transfer now or complete the business request first; no transfer has been sent.", "HO-01", details={"write_authorized": False}))
    index = len(state["history"])
    try:
        summary = build_summary(state, index - 1)
        # Check the actual wrapper too, before recording a dispatch.
        draft = json.loads(json.dumps(state))
        event(draft, {"kind": "dispatch", "call_id": f"handoff:{index}", "request_index": index - 1, "summary": summary})
        argument = json.dumps(draft, ensure_ascii=False, allow_nan=False)
        check_workflow_argument(argument)
    except ValueError:
        return reply(state, need("handoff_budget_exceeded", "The retained evidence exceeds the internal transfer budget; no transfer was sent.", "HO-01", details={"write_authorized": False}))
    event(state, {"kind": "dispatch", "call_id": f"handoff:{index}", "request_index": index - 1, "summary": summary})
    return Decision(calls=(ToolAction(id=f"handoff:{index}", name="handoff_workflow", arguments={"session_json": argument}),)), state


def run_handoff_workflow(state, client_api, claims):
    from support_agent.adapters.write_runtime import SessionClaims
    from support_agent.state import clone_state
    state = clone_state(state)
    current = state["handoff"]
    if current["status"] != "dispatched" or len(state["history"]) != current["request_index"] + 2:
        raise ValueError("An original human transfer dispatch is required")
    conversation = getattr(getattr(client_api, "context", None), "conversation_id", None)
    status, receipt, code = "rejected", None, "trusted_conversation_required"
    if isinstance(conversation, str) and conversation.strip() and isinstance(claims, SessionClaims):
        identity = hashlib.sha256(json.dumps({"request_index": current["request_index"], "summary": current["summary"]}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        with claims.lock:
            previous = claims.handoffs.get(conversation)
            if previous and (previous["status"] != "rejected" or current["request_index"] <= previous["request_index"] or not any(e.get("handoff_event", {}).get("call_id") == previous["call_id"] and e.get("handoff_event", {}).get("status") == "rejected" for e in state["history"])):
                status, code = "unknown", "handoff_claim_conflict"
            else:
                claims.handoffs[conversation] = {"identity": identity, "status": "sent", "request_index": current["request_index"], "call_id": current["call_id"]}
                status, code = "sent", ""
        if status == "sent":
            try:
                candidate = request_object(client_api, "POST", f"/v1/conversations/{quote(conversation, safe='')}/transfers", body={"summary": current["summary"]}, expected_status=201, mutates=True)
                if valid_receipt(candidate):
                    status, receipt = "accepted", candidate
                else:
                    status, code = "unknown", "invalid_transfer_receipt"
            except ClientAPIError as exc:
                status, code = ("unknown" if exc.outcome_unknown else "rejected"), exc.kind
            with claims.lock:
                claims.handoffs[conversation]["status"] = status
    else:
        conversation = None
    event(state, {"kind": "result", "call_id": current["call_id"], "status": status, "conversation_id": conversation, "receipt": receipt, "error_code": code})
    result = assessment(status)
    reply(state, result)
    return {"reply": result["message"], "state": state, "assessment": result}


def accept_handoff_result(state, outcomes):
    from support_agent.state import clone_state
    current = state["handoff"]
    try:
        if len(outcomes) != 1 or outcomes[0].id != current["call_id"] or outcomes[0].error or len(outcomes[0].content.encode("utf-8")) > MAX_WORKFLOW_RESULT_BYTES:
            raise ValueError("Missing or rejected transfer batch")
        payload = json.loads(outcomes[0].content)
        if not isinstance(payload, dict) or set(payload) != {"reply", "state", "assessment"}:
            raise ValueError("Malformed transfer payload")
        candidate = clone_state(payload["state"])
        prefix = state["history"]
        suffix = candidate["history"][len(prefix):]
        if (candidate["history"][:len(prefix)] != prefix or len(suffix) != 2 or "handoff_event" not in suffix[0]
                or suffix[0]["handoff_event"]["kind"] != "result" or "handoff_assessment" not in suffix[1]
                or payload["assessment"] != assessment(candidate["handoff"]["status"])
                or payload["reply"] != payload["assessment"]["message"]):
            raise ValueError("Transfer result changed its original evidence")
        # Accept only the two validated events, never arbitrary replacement state.
        event(state, suffix[0]["handoff_event"])
        return reply(state, payload["assessment"])
    except (TypeError, ValueError, KeyError):
        event(state, {"kind": "result", "call_id": current["call_id"], "status": "unknown", "conversation_id": None, "receipt": None, "error_code": "result_rejected"})
        return reply(state, assessment("unknown"))
