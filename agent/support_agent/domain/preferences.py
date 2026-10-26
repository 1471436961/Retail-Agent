"""Rank structured catalog preferences; customer language is interpreted by the model."""

import math

from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class RankingCriterion(BaseModel):
    """One explicit sort key; list position supplies its priority."""
    model_config = ConfigDict(extra="forbid", strict=True)

    field: Literal["price", "option"]
    option: str | None = None
    values: list[str] | None = None
    direction: Literal["ascending", "descending"] | None = None

    @model_validator(mode="after")
    def check_shape(self):
        if self.field == "price":
            if self.direction is None or self.option is not None or self.values is not None:
                raise ValueError("A price criterion needs an explicit direction and no option/values")
        elif (not self.option or not self.values or self.direction is not None or
              any(not value for value in self.values) or len(set(self.values)) != len(self.values)):
            raise ValueError("An option criterion needs its name and an ordered list of distinct values")
        return self


def ranking_criteria(sort_by):
    if not isinstance(sort_by, list):
        raise ValueError("sort_by must be an explicit list; use [] when no priority was stated")
    return [RankingCriterion.model_validate(criterion) for criterion in sort_by]


def _options(value):
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(option, str)
        for key, option in value.items()
    ):
        raise ValueError("Options must map catalog option names to string values")
    return dict(value)


def rank_variants(original_options, allowed_options, sort_by, variants):
    """Apply model-specified constraints and ordered criteria, without adding preferences."""
    original = _options(original_options)
    if not isinstance(allowed_options, dict) or any(
        not isinstance(key, str) or not key or (values is not None and (
            not isinstance(values, list) or not values or
            any(not isinstance(value, str) or not value for value in values)
        )) for key, values in allowed_options.items()
    ):
        raise ValueError("Allowed options map names to nonempty value lists, or null for an unrestricted option")
    constraints = {key: [value] for key, value in original.items()}
    constraints.update(allowed_options)
    criteria = ranking_criteria(sort_by)
    vocabulary = {key: {value} for key, value in original.items()}
    eligible, unavailable = [], []
    for variant in variants:
        options = _options(variant["options"])
        for key, value in options.items():
            vocabulary.setdefault(key, set()).add(value)
        if any(values is not None and options.get(key) not in values for key, values in constraints.items()):
            continue
        available = variant["available"]
        if type(available) is not bool:
            raise ValueError("Catalog availability must be a boolean")
        price = variant["price"]
        if type(price) not in (int, float) or (type(price) is float and not math.isfinite(price)):
            raise ValueError("Catalog price must be a finite number")
        (eligible if available else unavailable).append(dict(variant))
    for criterion in criteria:
        if criterion.field == "option" and criterion.option not in vocabulary:
            raise ValueError(f"Unknown ranking option {criterion.option!r}; catalog options: {sorted(vocabulary)}")

    def sort_key(row):
        keys = []
        for criterion in criteria:
            if criterion.field == "price":
                keys.append(row["price"] if criterion.direction == "ascending" else -row["price"])
            else:
                value = row["options"].get(criterion.option)
                keys.append(criterion.values.index(value) if value in criterion.values else len(criterion.values))
        return tuple(keys)

    def ranked(rows):
        rows.sort(key=sort_key)
        rank, previous = 0, None
        for row in rows:
            key = sort_key(row)
            if key != previous:
                rank += 1
            row["preference_rank"] = rank
            row["sort_values"] = list(key)
            previous = key
        return rows

    return {
        "effective_constraints": constraints,
        "ranking_criteria": [criterion.model_dump(exclude_none=True) for criterion in criteria],
        "ranked_candidates": ranked(eligible),
        "unavailable_matches": ranked(unavailable),
        "catalog_option_values": {key: sorted(values) for key, values in sorted(vocabulary.items())},
    }
