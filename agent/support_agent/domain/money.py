"""Local estimates compatible with the published U6 float/round contract.

These helpers do not select order items, authorize payments or write amounts.
Backend receipts remain authoritative. Other accounting paths are not covered.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal


def display_exact_amount(value: Decimal | str) -> str:
    """Display an exact decimal with at least two places, without rounding.

    Extra significant fractional digits survive; only insignificant trailing
    zeros are removed. This formatting does not compute any settlement amount.
    """
    number = value if isinstance(value, Decimal) else Decimal(value)
    if not number.is_finite():
        raise ValueError("Expected a finite exact decimal")
    whole, _, fraction = format(number, "f").partition(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


def _finite_float(value: int | float) -> float:
    """Accept finite JSON numbers without coercing bool or numeric strings."""
    if type(value) not in (int, float):
        raise TypeError("Expected a finite JSON number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("Number is outside the finite float range") from exc
    if not math.isfinite(result):
        raise ValueError("Expected a finite JSON number")
    return result


def finite_number(value: int | float) -> int | float:
    """Validate finite JSON numbers while retaining their original precision."""
    _finite_float(value)
    return value


def finite_amount(value: int | float) -> int | float:
    """Validate a nonnegative source price/balance/payment without rounding it."""
    if _finite_float(value) < 0:
        raise ValueError("Amount must be nonnegative")
    return value


def price_difference(replacements: Iterable[tuple[int | float, int | float]]) -> float:
    """Sum ``new_price - old_price`` in request order; round only the total.

Each pair is (old_price, new_price), already resolved by the caller. Keep
duplicates and original precision; do not sort, group or round individual
pairs. A positive result is an extra charge, a negative result is a refund
estimate. This function does not infer ID/occurrence matching or eligibility.
"""
    total = 0.0
    for old_price, new_price in replacements:
        total += _finite_float(new_price) - _finite_float(old_price)
        if not math.isfinite(total):
            raise ValueError("Price difference is outside the finite float range")
    return round(total, 2)


def round_gift_card_balance(updated_balance: int | float) -> float:
    """Round an already computed balance using the published Python rule.

The caller determines the debit/credit operation and its eligibility. This
helper only locks the documented rounding, not an unpublished update formula.
"""
    return round(_finite_float(updated_balance), 2)
