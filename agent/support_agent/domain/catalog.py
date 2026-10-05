"""Resolve selected original units and exact variants without ranking or I/O."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_HALF_UP

from support_agent.domain.money import finite_amount, price_difference
from support_agent.domain.rules import allow, deny, identifier, input_error, need, options


def _original_groups(items):
    if not isinstance(items, list) or not items:
        raise ValueError("Original order items are required")
    groups = {}
    for item in items:
        if (not isinstance(item, dict) or any(not identifier(item.get(k)) for k in ("item_id", "product_id", "name"))
                or not options(item.get("options"))):
            raise ValueError("Invalid original item")
        finite_amount(item.get("price"))
        groups.setdefault(item["item_id"], []).append(item)
    return groups


def _selected(items, ids):
    """Identical copies are selectable by count; differing instances are not."""
    try:
        groups = _original_groups(items)
    except (TypeError, ValueError):
        return need("original_items_required", "Refresh the original item records and prices.", "MO-01", "U3")
    if ids is None:
        return need("item_ids_required", "Specify exact original item IDs as a list.", "U5")
    if not isinstance(ids, list) or any(not identifier(v) for v in ids):
        return input_error("invalid_item_ids", "Item IDs must be a list of nonempty strings.", "U5")
    if not ids:
        return deny("empty_item_selection", "At least one original unit must be selected.", "U5")
    for item_id, count in Counter(ids).items():
        if item_id not in groups:
            return deny("item_not_in_order", "A selected item does not belong to this order.", "ID-02", "U5")
        if count > len(groups[item_id]):
            return deny("quantity_exceeds_order", "Selected occurrences exceed the original order count.", "BN-01", "U5")
        first = groups[item_id][0]
        if any(any(copy[k] != first[k] for k in ("product_id", "price", "options", "name")) for copy in groups[item_id][1:]):
            return need("instance_selection_unavailable", "The same item ID has differing instances; no public line selector proves the requested choice.", "U5")
    return allow("original_units_resolved", "Original prices and requested occurrences are preserved.", "RT-01", "U5",
                 details={"items": [groups[item_id][0] for item_id in ids], "item_ids": ids})


def resolve_return_items(order_items, item_ids) -> dict:
    """Selection only: no refund aggregation algorithm or arrival assertion."""
    return _selected(order_items, item_ids)


def return_refund_basis(order_items, item_ids) -> dict:
    """Project display estimate, not a backend settlement instruction.

    Sum original JSON price spellings exactly, preserving selected occurrences,
    then display cents with half-up rounding. This deliberately does not alter
    the documented ordered float price-difference calculation. The return API
    accepts no amount and its receipt cannot prove settlement or arrival.
    """
    selection = resolve_return_items(order_items, item_ids)
    if selection["decision"] != "allow":
        return selection
    with localcontext() as context:
        # JSON finite doubles can span 309 integer and 324 fractional digits.
        context.prec = 700 + len(str(len(item_ids)))
        exact = sum((Decimal(str(i["price"])) for i in selection["details"]["items"]), Decimal(0))
        estimate = float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    try:
        finite_amount(estimate)
    except (TypeError, ValueError):
        return need("refund_estimate_unrepresentable", "The selected price total cannot be displayed safely.", "MO-01")
    return allow("original_price_refund_estimate",
                "Estimated refund from selected original prices; backend settlement and arrival are not verified.",
                "RT-01", "MO-01", "U6",
                details={"items": selection["details"]["items"], "item_ids": selection["details"]["item_ids"],
                         "aggregate_amount": estimate, "exact_price_sum": str(exact),
                         "estimate_method": "original_prices_decimal_sum_half_up_cents",
                         "amount_is_estimate": True, "aggregation_contract_verified": False,
                         "settlement_verified": False})


def _variants(products):
    if not isinstance(products, list):
        raise ValueError("Product envelopes are required")
    variants, product_ids = {}, set()
    for product in products:
        if (not isinstance(product, dict) or not identifier(product.get("product_id"))
                or not isinstance(product.get("name"), str) or not isinstance(product.get("items"), list)
                or product["product_id"] in product_ids):
            raise ValueError("Invalid or repeated product envelope")
        product_ids.add(product["product_id"])
        for item in product["items"]:
            if (not isinstance(item, dict) or not identifier(item.get("item_id")) or item["item_id"] in variants
                    or type(item.get("available")) is not bool or not options(item.get("options"))):
                raise ValueError("Invalid or repeated catalog variant")
            finite_amount(item.get("price"))
            # CatalogItem has no product_id; membership comes from its envelope.
            variants[item["item_id"]] = (product["product_id"], item)
    return variants


def resolve_replacements(order_items, replacements, products, *, requested_options=None, sequential_matching=True) -> dict:
    """Check a selected full list; M5.1 candidate_selection supplies alternatives.

    requested_options has one dict per occurrence, reflecting only explicitly
    requested attribute changes. Omitted attributes must retain original values.
    Only ID pairs belong in future backend requests; no quantity/occurrence field.
    """
    if type(sequential_matching) is not bool:
        return input_error("invalid_matching_mode", "The trusted matching mode must be boolean.", "U5")
    if replacements is None:
        return need("replacement_list_required", "Specify the complete original/replacement ID list.", "IT-01", "U5")
    if isinstance(replacements, list) and any(isinstance(r, dict) and "quantity" in r for r in replacements):
        return deny("quantity_change_unsupported", "Changing quantities is outside the supported item change.", "BN-01")
    if (not isinstance(replacements, list) or any(not isinstance(r, dict)
            or set(r) != {"existing_item_id", "replacement_item_id"}
            or any(not identifier(v) for v in r.values()) for r in replacements)):
        return input_error("invalid_replacement_list", "Use exact original/replacement ID pairs without extra fields.", "IT-01", "U5")
    selection = _selected(order_items, [r["existing_item_id"] for r in replacements])
    if selection["decision"] != "allow":
        return selection
    if requested_options is None:
        return need("requested_options_required", "Identify the requested attribute changes for every selected occurrence.", "IT-01", "EX-01")
    if (not isinstance(requested_options, list) or len(requested_options) != len(replacements)
            or any(not options(v) for v in requested_options)):
        return input_error("invalid_requested_options", "Attribute changes must match the complete ordered replacement list.", "IT-01")
    try:
        variants = _variants(products)
    except (TypeError, ValueError):
        return need("catalog_facts_required", "Refresh complete product envelopes, variants, availability and prices.", "IT-01", "U3")
    pairs = []
    prior_targets = set()
    for original, replacement, changes in zip(selection["details"]["items"], replacements, requested_options):
        source_id, target_id = replacement["existing_item_id"], replacement["replacement_item_id"]
        # Pending modification mutates the item list between first-ID matches.
        # Exchange only records an application; every source is an original unit.
        if sequential_matching and source_id in prior_targets:
            return need("sequential_match_ambiguous", "An earlier replacement introduces a later source ID; first-ID matching cannot prove original-unit intent.", "U5")
        if target_id not in variants:
            return need("target_variant_required", "The exact target variant and its product membership are missing.", "IT-01")
        product_id, target = variants[target_id]
        if product_id != original["product_id"]:
            return deny("different_product", "Only a variant of the same product can replace this item.", "IT-01", "EX-01")
        if target_id == source_id:
            return deny("unchanged_variant", "An item change must select a different variant.", "IT-01")
        if not target["available"]:
            return deny("variant_unavailable", "Unavailable variants cannot enter the replacement list.", "IT-01", "EX-01")
        if set(changes) - set(original["options"]):
            return need("unknown_option", "The requested attribute is not present in the original specification.", "IT-01")
        expected = {**original["options"], **changes}
        if target["options"] != expected:
            return deny("specification_mismatch", "The target must satisfy requested changes and retain every other attribute.", "IT-01", "EX-01")
        pairs.append([original["price"], target["price"]])
        prior_targets.add(target_id)
    try:
        difference = price_difference(pairs)
    except (TypeError, ValueError):
        return need("invalid_difference", "The difference cannot be represented safely as a finite quote.", "MO-01", "U6")
    return allow("replacements_eligible", "The complete selected list meets product, availability, count and specification rules.", "IT-01", "EX-01", "U5", "U6",
                 details={"replacements": deepcopy(replacements), "price_pairs": pairs, "price_difference": difference,
                          "amount_kind": "estimate", "settlement_verified": False})
