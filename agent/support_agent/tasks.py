"""M3.4 internal request planning, not a model surface or a write scheduler.

Plans describe requested actions, never consent or completed operations. The
trusted producer must submit the returned assistant text and state together;
history authenticity/actual delivery remain the M3.5 threat-model boundary.
"""
import json

from support_agent.domain.orders import order_state_rule
from support_agent.domain.rules import allow, deny, need
from support_agent.domain.task_graph import InvalidTaskPlan, build_task_graph, normalize_requests
from support_agent.protocol import Decision


def render_task_plan(nodes):
    lines = ["Requested operations and dependencies (this is not a confirmation recap):"]
    numbers = {n["id"]: i for i, n in enumerate(nodes, 1)}
    for i, node in enumerate(nodes, 1):
        target = node["target"]
        lines.append(f"Task {i}: {node['action']} for customer {target['customer_id']}"
                     + (f", order {target['order_id']}" if "order_id" in target else ", default address record"))
        if node["depends_on"]:
            lines.append("Requires verified completion of task(s) " + ", ".join(str(numbers[d]) for d in node["depends_on"]) + ".")
        if node["conflicts"]:
            lines.append("Choose between conflicting task(s) " + ", ".join(str(numbers[c["task_id"]]) for c in node["conflicts"]) + " before proceeding.")
    lines.append("Each selected operation still requires a complete proposal, user confirmation and pre-write verification. No operation has been executed.")
    return "\n".join(lines)


def _request_scope(history, requests):
    # Reuse the accepted M2 prefix and its single strict identity implementation.
    from support_agent.proposals import _clean_read_history
    from support_agent.state import initial_state
    from support_agent.adapters.read_api import customer_order_ids
    prefix = initial_state(_clean_read_history(history))
    if (not prefix["identity"]["verified"] or not prefix["identity_evidence"]
            or prefix["pending_calls"] or prefix["handoff"]["status"] != "not_requested"):
        raise InvalidTaskPlan("Plan requires a verified idle session")
    owned = customer_order_ids(prefix["customer_record"])
    for request in requests:
        target = request["target"]
        if (target["customer_id"] != prefix["identity"]["customer_id"]
                or ("order_id" in target and target["order_id"] not in owned)):
            raise InvalidTaskPlan("Task target must be in the verified customer's record scope")


def restore_task_plan(state, index):
    entry = state["history"][index]
    if not isinstance(entry, dict) or set(entry) != {"role", "content", "task_plan"} or entry["role"] != "assistant":
        raise InvalidTaskPlan("Only an assistant plan entry can describe tasks")
    event = entry["task_plan"]
    if not isinstance(event, dict) or set(event) != {"requests", "request_index"}:
        raise InvalidTaskPlan("Invalid task plan metadata")
    request_index = next((i for i in range(index - 1, -1, -1) if state["history"][i]["role"] == "user"), None)
    if type(event["request_index"]) is not int or event["request_index"] != request_index:
        raise InvalidTaskPlan("Plan must bind the preceding actual user request")
    requests = normalize_requests(event["requests"])
    _request_scope(state["history"][:index], requests)
    nodes = build_task_graph(requests, index, request_index)
    if entry["content"] != render_task_plan(nodes):
        raise InvalidTaskPlan("Task plan text differs from recorded requests and edges")
    state["tasks"] = nodes


def validate_tasks(state):
    replay = {"history": [], "tasks": []}
    for index, entry in enumerate(state["history"]):
        replay["history"].append(entry)
        if "task_plan" in entry:
            restore_task_plan(replay, index)
    if json.dumps(replay["tasks"], sort_keys=True, allow_nan=False) != json.dumps(state["tasks"], sort_keys=True, allow_nan=False):
        raise InvalidTaskPlan("Tasks differ from original request plan evidence")


def present_task_plan(state, requests):
    """Replace the requested scope atomically; omission is not completion.

    A future producer must resolve the user's actual change of plan. This
    bounded structured entry does not parse business requests automatically.
    A plan never changes or creates any proposal/confirmation.
    """
    from support_agent.state import clone_state
    state = clone_state(state)
    requests = normalize_requests(requests)
    _request_scope(state["history"], requests)
    request_index = next((i for i in range(len(state["history"]) - 1, -1, -1) if state["history"][i]["role"] == "user"), None)
    if request_index is None:
        raise InvalidTaskPlan("A preceding actual user request is required")
    index = len(state["history"])
    nodes = build_task_graph(requests, index, request_index)
    text = render_task_plan(nodes)
    state["history"].append({"role": "assistant", "content": text,
                             "task_plan": {"requests": requests, "request_index": request_index}})
    restore_task_plan(state, index)
    return Decision(text=text), clone_state(state)


def _unresolved_order_read(history, target):
    """A failed attempt to refresh this order cannot become fresh task facts."""
    calls, unresolved = {}, False
    for entry in history:
        if entry["role"] == "assistant":
            for call in entry.get("tool_calls", []):
                args = call["arguments"]
                if (args.get("customer_id") == target["customer_id"]
                        and ((call["name"] == "get_order" and args.get("order_id") == target.get("order_id"))
                             or (call["name"] == "list_customer_orders" and not args.get("status")))):
                    calls[call["id"]] = call
                    unresolved = True
        results = entry.get("tool_messages", []) if entry["role"] == "tools" else [entry] if entry["role"] == "tool" else []
        for result in results:
            if result["id"] in calls:
                body = json.loads(result["content"])
                unresolved = result["error"] or "read_result_status" in body
    return unresolved


def inspect_task_plan(state):
    """Return independent candidates for M3.5 assessment, never write permission.

    This milestone has no business result reducer. Dependent tasks remain
    blocked until later workflows supply verified completion; confirmation,
    planning, read success and removing a task are not completion evidence.
    """
    from support_agent.state import clone_state, InvalidState
    from support_agent.proposals import _current_records, _scope_facts, check_confirmation
    def outcome(builder, code, message, **details):
        return builder(code, message, "ST-02", "ST-03", "CF-01", details={"write_authorized": False, **details})
    try:
        state = clone_state(state)
    except (TypeError, ValueError, KeyError, InvalidState):
        return outcome(deny, "invalid_state", "Task evidence is invalid; processing is stopped.", state_error=True)
    if state["handoff"]["status"] != "not_requested":
        return outcome(deny, "handoff_blocks_tasks", "Handoff blocks further task planning.")
    if state["pending_calls"]:
        return outcome(need, "pending_reads", "Resolve the complete pending read batch first.")
    if not state["tasks"]:
        return outcome(need, "task_plan_required", "A structured request plan is required.")
    current = _current_records(state)
    results = []
    for node in state["tasks"]:
        gate = None
        proposal = next((p for p in current if p["spec"]["action"] == node["action"] and p["spec"]["target"] == node["target"]), None)
        if node["conflicts"]:
            gate = outcome(need, node["conflicts"][0]["code"], "Resolve mutually exclusive same-order requests before submission.")
        elif any(o["mutates"] and o["status"] == "succeeded" and not o["persistence_unresolved"] and o["sent_index"] > node["plan_index"]
                 and o["spec"]["action"] == node["action"] and o["spec"]["target"] == node["target"] for o in state["operations"]):
            gate = outcome(allow, "task_completed", "A recorded send, matching receipt and owned strong readback prove completion.")
        else:
            try:
                facts = _scope_facts(state["history"], node, state_only=True)
                eligibility = (order_state_rule(facts["order"], node["action"]) if facts["order"] is not None
                               else allow("default_record_eligible", "Default address is an independent record.", "AD-01"))
                if eligibility["decision"] != "allow":
                    gate = {**eligibility, "details": {**eligibility["details"], "write_authorized": False}}
                elif facts["order"] is not None and _unresolved_order_read(state["history"], node["target"]):
                    gate = outcome(need, "order_read_unresolved", "The latest attempt to read this order was not accepted; investigate before proceeding.")
            except (TypeError, ValueError, KeyError):
                gate = outcome(need, "task_facts_required", "Accepted identity and owned record facts are required.")
        if gate is None:
            if proposal is None:
                gate = outcome(need, "proposal_required", "Prepare a complete proposal for this specific requested operation.")
            else:
                consent = check_confirmation(state, proposal["version"], proposal["spec"])
                gate = {**consent, "details": {**consent["details"], "write_authorized": False}}
                if consent["decision"] == "allow":
                    gate = outcome(allow, "preflight_candidate", "This independent confirmed operation is a candidate for pre-write verification only.")
        results.append({**node, "proposal_version": proposal["version"] if proposal else None, "assessment": gate})
    by_id = {r["id"]: r for r in results}
    for node in results:
        unresolved = [d for d in node["depends_on"] if by_id[d]["assessment"]["code"] != "task_completed"]
        if unresolved and not node["conflicts"]:
            blocked = any(by_id[d]["assessment"]["decision"] == "deny" for d in unresolved)
            # Preserve the affected task's own denial/condition/fact diagnostics.
            if node["assessment"]["decision"] == "allow" and node["assessment"]["code"] != "task_completed":
                node["assessment"] = outcome(need, "dependency_blocked" if blocked else "dependency_result_required",
                    "Same-order prerequisites need verified completion; consent and read receipts do not complete them.",
                    depends_on=unresolved)
    candidates = [r["id"] for r in results if r["assessment"]["code"] == "preflight_candidate"]
    return outcome(allow, "task_plan_assessed", "Each record has its own dependency and confirmation assessment.",
                   tasks=results, preflight_candidates=candidates)
