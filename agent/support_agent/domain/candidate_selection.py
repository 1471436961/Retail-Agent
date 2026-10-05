"""Deterministic M5.1 selection, never a proposal, consent or business write.

Criteria are explicit normalized customer choices. List order is meaningful for
preferences, fallback branches and ranking priorities; catalog order is not a
tie breaker. Unknown comparison semantics are information gaps, not no stock.
"""
from decimal import Context, Decimal, InvalidOperation, localcontext
import re
from types import MappingProxyType

from support_agent.domain.catalog import _selected, _variants
from support_agent.domain.rules import allow, identifier, input_error, need


class InvalidCriteria(ValueError):
    pass


class ComparisonUnavailable(ValueError):
    pass


_UNITS = MappingProxyType({"ml": ("volume", 1), "l": ("volume", 1000),
          "gb": ("storage", 1), "tb": ("storage", 1000),
          "g": ("mass", 1), "kg": ("mass", 1000),
          "mm": ("length", 1), "cm": ("length", 10), "m": ("length", 1000),
          "inch": ("length", Decimal("25.4")), "in": ("length", Decimal("25.4")),
          "inches": ("length", Decimal("25.4"))})


def _number(value):
    if type(value) in (int, float):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().casefold()
    else:
        raise ComparisonUnavailable("A numeric value is required")
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*([a-z%×]+)?", text)
    if not match:
        raise ComparisonUnavailable("An option has no documented numeric interpretation")
    try:
        number = Decimal(match[1])
    except InvalidOperation as exc:
        raise ComparisonUnavailable("Invalid numeric value") from exc
    if number and not -324 <= number.adjusted() <= 308:
        raise ComparisonUnavailable("Measurement exceeds the supported finite-number comparison range")
    unit = match[2] or ""
    # Unlisted units may only be compared with the identical unit. No implicit
    # CPU, difficulty, quality or decimal/binary storage hierarchy is invented.
    dimension, multiplier = _UNITS.get(unit, (unit, 1))
    # Own arithmetic context, including exponent limits/traps; callers may have
    # changed their Decimal context. Precision preserves all input digits and
    # exact unit conversion, rather than rounding a measurement to select it.
    with localcontext(Context(prec=max(700, len(number.as_tuple().digits) + 10))):
        return (number if number else Decimal(0)) * multiplier, dimension


def _field(item, field):
    if field == "price":
        return item["price"]
    if field not in item["options"]:
        raise ComparisonUnavailable("A required option is missing")
    return item["options"][field]


def _compare(left, right, order=None):
    if order is not None:
        if left not in order or right not in order:
            raise ComparisonUnavailable("An ordinal value is outside the explicit ordering")
        a, b = order.index(left), order.index(right)
    else:
        a, unit_a = _number(left)
        b, unit_b = _number(right)
        if unit_a != unit_b:
            raise ComparisonUnavailable("Numeric units are incompatible")
    return (a > b) - (a < b)


def _sequence(value):
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value) and len(value) == len(set(value))


def _validate_branch(branch, option_names):
    if not isinstance(branch, dict) or set(branch) != {"hard", "change", "relax"}:
        raise InvalidCriteria("Each branch requires hard/change/relax")
    if any(not _sequence(branch[k]) or not set(branch[k]) <= option_names for k in ("change", "relax")):
        raise InvalidCriteria("Changed and relaxed attributes must exist on the original item")
    if set(branch["change"]) & set(branch["relax"]):
        raise InvalidCriteria("Change and relax must not overlap")
    if not isinstance(branch["hard"], list):
        raise InvalidCriteria("Hard constraints must be a list")
    for predicate in branch["hard"]:
        if (not isinstance(predicate, dict) or not {"field", "op", "value"} <= set(predicate)
                or set(predicate) - {"field", "op", "value", "order"}
                or predicate["field"] not in option_names | {"price"}
                or predicate["op"] not in {"eq", "in", "lt", "lte", "gt", "gte"}):
            raise InvalidCriteria("Invalid hard constraint")
        value = predicate["value"]
        if predicate["op"] == "in":
            if not isinstance(value, list) or not value:
                raise InvalidCriteria("Membership needs a nonempty value list")
            values = value
        else:
            values = [value]
        for v in values:
            if isinstance(v, dict):
                if set(v) != {"original"} or v["original"] not in option_names | {"price"}:
                    raise InvalidCriteria("An original reference must name an existing field")
            elif type(v) not in (str, int, float):
                raise InvalidCriteria("Constraint values must be strings, finite numbers or original references")
            if type(v) in (int, float):
                _number(v)
        if "order" in predicate and (predicate["op"] in {"eq", "in"} or not _sequence(predicate["order"]) or not predicate["order"]):
            raise InvalidCriteria("An explicit ordinal order belongs to a comparison")


def _validate(criteria, option_names):
    keys = {"hard", "change", "relax", "preferences", "fallbacks", "ranking"}
    if not isinstance(criteria, dict) or set(criteria) != keys:
        raise InvalidCriteria("Criteria require exactly hard/change/relax/preferences/fallbacks/ranking")
    _validate_branch({k: criteria[k] for k in ("hard", "change", "relax")}, option_names)
    for key in ("preferences", "fallbacks", "ranking"):
        if not isinstance(criteria[key], list):
            raise InvalidCriteria("Preference, fallback and ranking lists are required")
    for branch in criteria["fallbacks"]:
        _validate_branch(branch, option_names)
    for pref in criteria["preferences"]:
        if (not isinstance(pref, dict) or set(pref) != {"field", "tiers"} or pref["field"] not in option_names
                or not isinstance(pref["tiers"], list) or not pref["tiers"]
                or any(not _sequence(tier) or not tier for tier in pref["tiers"])):
            raise InvalidCriteria("Preferences require ordered, nonempty tiers of values")
        flat = [v for tier in pref["tiers"] for v in tier]
        if len(flat) != len(set(flat)):
            raise InvalidCriteria("Preference tiers must not repeat a value")
    fields = []
    for rank in criteria["ranking"]:
        if (not isinstance(rank, dict) or not {"field", "direction"} <= set(rank)
                or set(rank) - {"field", "direction", "order"}
                or rank["field"] not in option_names | {"price"} or rank["direction"] not in {"min", "max"}
                or ("order" in rank and (not _sequence(rank["order"]) or not rank["order"]))):
            raise InvalidCriteria("Ranking requires an explicit ordered list of min/max criteria")
        fields.append(rank["field"])
    if len(fields) != len(set(fields)):
        raise InvalidCriteria("Ranking priorities must not repeat a field")


def _matches(item, predicate, original):
    left, right, op = _field(item, predicate["field"]), predicate["value"], predicate["op"]
    def resolve(value):
        return _field(original, value["original"]) if isinstance(value, dict) else value
    if op in {"eq", "in"}:
        values = [resolve(value) for value in (right if op == "in" else [right])]
        return any((_compare(left, v) == 0 if predicate["field"] == "price" else left == v) for v in values)
    comparison = _compare(left, resolve(right), predicate.get("order"))
    return {"lt": comparison < 0, "lte": comparison <= 0, "gt": comparison > 0, "gte": comparison >= 0}[op]


def _select_candidates(order_items, item_id, products, criteria):
    """Select one original unit's alternatives; full-list assembly is M5.2.

    Fallbacks are complete alternate branches explicitly supplied by the user,
    tried only after all previous branches have zero eligible candidates. They
    may replace primary hard constraints; omitted original attributes remain
    preserved independently in each branch. A single result still needs a full
    proposal and fresh consent before any write.
    """
    if not identifier(item_id):
        return input_error("invalid_source_item", "Specify an original item ID.", "IT-01")
    selected = _selected(order_items, [item_id])
    if selected["decision"] != "allow":
        return selected
    original = selected["details"]["items"][0]
    try:
        _validate(criteria, set(original["options"]))
    except (InvalidCriteria, ComparisonUnavailable, TypeError, ValueError):
        return input_error("invalid_selection_criteria", "Repair the explicit selection criteria; do not infer customer choices.", "IT-01", "U4")
    try:
        variants = _variants(products)
    except (TypeError, ValueError, OverflowError):
        return need("catalog_facts_required", "Complete validated product facts are required.", "U4")
    if original["product_id"] not in {p["product_id"] for p in products}:
        return need("product_catalog_required", "Read the original product's complete catalog.", "IT-01")
    alternatives = [item for product_id, item in variants.values() if product_id == original["product_id"] and item["item_id"] != item_id]
    trace, pool, branch_index = [], [], None
    branches = [{k: criteria[k] for k in ("hard", "change", "relax")}] + criteria["fallbacks"]
    for index, branch in enumerate(branches):
        hard, uncertain = [], []
        for item in alternatives:
            matches, unknown = [], False
            for predicate in branch["hard"]:
                try:
                    matches.append(_matches(item, predicate, original))
                except ComparisonUnavailable:
                    unknown = True
            if False in matches:
                continue  # A definite hard exclusion wins over unrelated unknowns.
            if unknown:
                uncertain.append(item)
            else:
                hard.append(item)
        retained = set(original["options"]) - set(branch["change"]) - set(branch["relax"])
        def eligible(item):
            return (item["available"] and set(item["options"]) == set(original["options"])
                    and all(item["options"][k] == original["options"][k] for k in retained))
        pool = [item for item in hard if eligible(item)]
        unknown = [item for item in uncertain if eligible(item)]
        trace.append({"branch": index, "hard_matches": len(hard), "in_stock": sum(i["available"] for i in hard),
                      "preserved_matches": len(pool), "unresolved_comparisons": len(unknown)})
        if unknown:
            return need("comparison_unavailable", "Clarify numeric units or the explicit ordinal ordering before selection or fallback.", "U4", details={"trace": trace, "write_authorized": False})
        if pool:
            branch_index = index
            break
    details = {"original": original, "criteria": criteria, "branch": branch_index, "fallback_used": branch_index is not None and branch_index > 0,
               "trace": trace, "eligible_candidates": pool, "write_authorized": False}
    if not pool:
        return need("no_eligible_candidates", "No alternative satisfies the explicit branches; ask before relaxing another attribute.", "IT-01", details=details)
    finalists = pool
    details.update(preference_trace=[], ranking_trace=[])
    for pref in criteria["preferences"]:
        scores = [next((i for i, tier in enumerate(pref["tiers"]) if item["options"][pref["field"]] in tier), len(pref["tiers"])) for item in finalists]
        best = min(scores)
        finalists = [item for item, score in zip(finalists, scores) if score == best]
        details["preference_trace"].append({"field": pref["field"], "tier": best if best < len(pref["tiers"]) else None,
                                            "remaining_ids": [item["item_id"] for item in finalists]})
    try:
        for rank in criteria["ranking"]:
            if len(finalists) < 2:
                break
            best = finalists[0]
            for item in finalists[1:]:
                comparison = _compare(_field(item, rank["field"]), _field(best, rank["field"]), rank.get("order"))
                if (rank["direction"] == "min" and comparison < 0) or (rank["direction"] == "max" and comparison > 0):
                    best = item
            finalists = [item for item in finalists if _compare(_field(item, rank["field"]), _field(best, rank["field"]), rank.get("order")) == 0]
            details["ranking_trace"].append({"field": rank["field"], "direction": rank["direction"], "best_value": _field(best, rank["field"]),
                                          "remaining_ids": [item["item_id"] for item in finalists]})
    except ComparisonUnavailable as error:
        # These are the candidates still under consideration after preferences
        # and completed ranking priorities, not a selected/authorized target.
        details.update(finalists=finalists, selected=None,
                       comparison_field=rank["field"], comparison_reason=str(error))
        return need("comparison_unavailable", "Clarify the ranking measurement or ordinal order.", "U4", details=details)
    details.update(finalists=finalists, selected=finalists[0] if len(finalists) == 1 else None)
    if len(finalists) != 1:
        return need("candidate_choice_required", "Several candidates remain tied. Which candidate do you prefer, or which attribute should take priority?", "IT-01", details=details)
    return allow("candidate_selected", "One candidate matches; this is not a complete proposal or write authorization.", "IT-01", "U4", details=details)


def select_candidates(order_items, item_id, products, criteria):
    """Public JSON decision; every outcome explicitly carries no write license."""
    result = _select_candidates(order_items, item_id, products, criteria)
    result["details"]["write_authorized"] = False
    return result
