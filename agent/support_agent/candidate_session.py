"""Internal M5.1 entry over canonical user/read evidence, with no API access.

The current default dialogue does not parse arbitrary shopping language. A
trusted caller supplies only the real user history index, not criteria or facts.
The next complete-item producer can reuse the pure selector after its intake.
"""
import json

from support_agent.workflow_registry import WORKFLOW_KINDS
from support_agent.adapters.read_api import customer_order_ids
from support_agent.domain.candidate_selection import select_candidates
from support_agent.domain.catalog import _selected
from support_agent.domain.rules import identifier, input_error, need
from support_agent.state import clone_state


def _assess_candidates(state, request_index):
    state = clone_state(state)
    blocked = lambda code, text: need(code, text, "ID-01", "U4", details={"write_authorized": False})
    if state["handoff"]["status"] not in {"not_requested", "rejected"}:
        return blocked("handoff_blocks_selection", "The handoff prevents further business processing."), state
    if state["pending_calls"] or state.get("handoff_pending") or any(state.get(k + "_pending") for k in WORKFLOW_KINDS):
        return blocked("pending_workflow", "Resolve the pending batch before assessing candidates."), state
    if not state["identity"]["verified"] or not state["identity_evidence"]:
        return blocked("identity_required", "Independent verification is required."), state
    latest_user = next((i for i in range(len(state["history"]) - 1, -1, -1) if state["history"][i]["role"] == "user"), None)
    if type(request_index) is not int or request_index != latest_user:
        return input_error("actual_selection_request_required", "Use the latest real user request index.", "ID-01"), state
    try:
        envelope = json.loads(state["history"][request_index]["content"])
        if not isinstance(envelope, dict) or set(envelope) != {"candidate_selection"}:
            raise ValueError()
        request = envelope["candidate_selection"]
        if not isinstance(request, dict) or set(request) != {"order_id", "item_id", "criteria"} or not all(identifier(request[k]) for k in ("order_id", "item_id")):
            raise ValueError()
    except (TypeError, ValueError):
        return input_error("invalid_selection_request", "Provide candidate_selection with order_id/item_id/criteria in the real user message.", "U4"), state
    if request["order_id"] not in customer_order_ids(state["customer_record"]):
        return input_error("order_not_owned", "The order is outside the verified customer's references.", "ID-02"), state
    # clone_state has already validated complete tool batches and provenance.
    # Operations still record rejected/missing attempts whose bodies were erased;
    # those attempts must override earlier facts instead of enabling a fallback.
    bodies, calls = {}, {}
    for entry in state["history"]:
        if entry["role"] == "assistant":
            calls.update({c["id"]: c for c in entry.get("tool_calls", [])})
        results = entry.get("tool_messages", []) if entry["role"] == "tools" else [entry] if entry["role"] == "tool" else []
        for item in results:
            if not item["error"]:
                body = json.loads(item["content"])
                if "read_result_status" not in body:
                    bodies[item["id"]] = body
    order = None
    for operation in state["operations"]:
        if operation["mutates"]:
            continue
        call = calls[operation["call_id"]]
        name, args = call["name"], call["arguments"]
        body = bodies.get(operation["call_id"]) if operation["status"] == "succeeded" else None
        if name == "get_order" and args["order_id"] == request["order_id"]:
            order = body
        elif name == "list_customer_orders":
            match = next((o for o in (body or {}).get("orders", []) if o["order_id"] == request["order_id"]), None)
            if match is not None or not args["status"]:
                order = match
    if order is None:
        return blocked("order_read_required", "A currently resolved owned order read is required."), state
    selected = _selected(order["items"], [request["item_id"]])
    if selected["decision"] != "allow":
        return selected, state
    product_id = selected["details"]["items"][0]["product_id"]
    product, known_members = None, {request["item_id"]}
    for operation in state["operations"]:
        if operation["mutates"]:
            continue
        call = calls[operation["call_id"]]
        name, args = call["name"], call["arguments"]
        body = bodies.get(operation["call_id"]) if operation["status"] == "succeeded" else None
        if name == "get_product" and args["product_id"] == product_id:
            product = body
            if body is not None:
                known_members.update(i["item_id"] for i in body["items"])
        elif name == "get_item" and args["item_id"] in known_members:
            if body is None:
                product = None
            elif product is not None:
                product["items"] = [body if i["item_id"] == args["item_id"] else i for i in product["items"]]
    if product is None:
        return blocked("product_read_required", "Read the complete original product; individual variants cannot prove no candidates exist."), state
    # Product is local replay data, never copied into the canonical history.
    return select_candidates(order["items"], request["item_id"], [product], request["criteria"]), state


def assess_candidates(state, request_index):
    """Return a diagnostic and unchanged cloned state, never a write license."""
    result, state = _assess_candidates(state, request_index)
    result["details"]["write_authorized"] = False
    return result, state
