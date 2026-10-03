"""Exact teaching states and action eligibility; no API, confirmation or writes."""
from support_agent.domain.rules import allow, deny, identifier, input_error, need

ORDER_STATUSES = frozenset({"pending", "pending (items modified)", "processed", "delivered",
                            "cancelled", "exchange requested", "return requested"})
ORDER_ACTIONS = frozenset({"shipping_address", "payment_method", "cancel", "modify_items", "return", "exchange"})
PENDING_ACTIONS = frozenset({"shipping_address", "payment_method", "cancel", "modify_items"})


def capability_rule(action: str) -> dict:
    if not isinstance(action, str):
        return input_error("invalid_action", "Action must be a string.", "BN-01")
    if action not in ORDER_ACTIONS | {"default_shipping_address", "transfer"}:
        return deny("unsupported_action", "This action is outside the customer-care surface.", "BN-01")
    return allow("supported_action", "The action has a documented service surface; other gates still apply.", "BN-01")


def order_state_rule(order: dict, action: str) -> dict:
    """Consume accepted order facts; caller must retain the M2 identity/owner gate.

    Tracking IDs do not supply shipment dates or an undocumented shipped flag.
    This only assesses current state, not freshness, complete parameters or consent.
    The full fulfillment-conflict guard belongs to M3.5 pre-write refresh checks.
    """
    capability = capability_rule(action)
    if capability["decision"] != "allow":
        return capability
    if action not in ORDER_ACTIONS:
        return deny("not_order_action", "Default address and transfer are separate records/actions.", "AD-01", "HO-01")
    if not isinstance(order, dict) or not identifier(order.get("order_id")) or not identifier(order.get("customer_id")):
        return need("order_facts_required", "An accepted order record is required.", "ID-02")
    status = order.get("status")
    if not isinstance(status, str) or status not in ORDER_STATUSES:
        return need("unknown_order_state", "Refresh and investigate the exact backend state; do not infer it.", "MO-01", "U6")
    for field, expected in (("cancellation", "cancelled"), ("return_request", "return requested"), ("exchange", "exchange requested")):
        receipt = order.get(field)
        if receipt is not None and (not isinstance(receipt, dict) or status != expected):
            return need("contradictory_order_facts", "State and operation records disagree; investigate before proceeding.", "MO-01", "U6")
    if status == "pending (items modified)":
        return deny("items_modified_lock", "The one-shot item change has locked further order changes and cancellation.", "ST-02")
    if status in {"return requested", "exchange requested"}:
        message = ("A submitted return/exchange cannot be appended or bypassed with another request."
                   if action in {"return", "exchange"} else
                   f"The order is {status}; {action} requires an eligible pending order.")
        return deny("return_exchange_already_requested", message, "ST-03", "ST-01",
                    details={"status": status, "action": action})
    if status == "cancelled":
        return deny("order_cancelled", "A cancelled order cannot be restored or changed.", "ST-04")
    if status == "processed":
        return deny("order_processed", "Pending changes are unavailable; return/exchange requires backend delivered status.", "ST-01", "ST-03")
    permitted = PENDING_ACTIONS if status == "pending" else {"return", "exchange"}
    if action not in permitted:
        return deny("action_not_allowed_in_state", "This action is not permitted in the exact current order state.", "ST-01", "ST-03")
    return allow("state_eligible", "State permits assessing this action; eligibility does not authorize a write.", "ST-01", "ST-03",
                 details={"order_id": order["order_id"], "status": status, "action": action})
