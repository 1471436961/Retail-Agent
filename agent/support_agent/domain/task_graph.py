"""Deterministic task edges; no consent, execution or inferred completion."""
import json

from support_agent.domain.orders import ORDER_ACTIONS
from support_agent.domain.rules import identifier


class InvalidTaskPlan(ValueError):
    """A malformed request plan must not replace the current plan."""


def normalize_requests(requests):
    if not isinstance(requests, list) or not requests:
        raise InvalidTaskPlan("A nonempty task request list is required")
    try:
        copied = json.loads(json.dumps(requests, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvalidTaskPlan("Task requests must be JSON values") from exc
    seen = set()
    for request in copied:
        if not isinstance(request, dict) or set(request) != {"action", "target"}:
            raise InvalidTaskPlan("A task request contains only action and target")
        action, target = request["action"], request["target"]
        if not isinstance(action, str) or action not in ORDER_ACTIONS | {"default_shipping_address"}:
            raise InvalidTaskPlan("Unsupported task action")
        fields = {"customer_id"} if action == "default_shipping_address" else {"customer_id", "order_id"}
        if not isinstance(target, dict) or set(target) != fields or any(not identifier(v) for v in target.values()):
            raise InvalidTaskPlan("An exact customer/record target is required")
        scope = (action, target["customer_id"], target.get("order_id"))
        if scope in seen:
            raise InvalidTaskPlan("Duplicate scopes must form one complete task, not split item tasks")
        seen.add(scope)
    return copied


def build_task_graph(requests, plan_index, request_index):
    """Address/payment precede the same order's one-shot item modification.

    Input order is display order only. No edge is invented between independent
    records. Conflict alternatives remain blocked until a new plan is chosen.
    """
    requests = normalize_requests(requests)
    if any(type(i) is not int or i < 0 for i in (plan_index, request_index)):
        raise InvalidTaskPlan("Plan and user indices must be nonnegative integers")
    nodes = [{"id": f"task:{plan_index}:{i}", **r, "plan_index": plan_index,
              "request_index": request_index, "depends_on": [], "conflicts": []}
             for i, r in enumerate(requests, 1)]
    for node in nodes:
        if "order_id" not in node["target"]:
            continue
        for other in nodes:
            if node["id"] == other["id"] or node["target"] != other["target"]:
                continue
            if node["action"] == "modify_items" and other["action"] in {"shipping_address", "payment_method"}:
                node["depends_on"].append(other["id"])
            reason = None
            if "cancel" in {node["action"], other["action"]}:
                reason = "same_order_cancel_conflict"
            elif {node["action"], other["action"]} == {"return", "exchange"}:
                reason = "same_order_return_exchange_conflict"
            if reason:
                node["conflicts"].append({"task_id": other["id"], "code": reason})
    return nodes
