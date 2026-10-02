"""Offline arithmetic boundaries from the published U6 compatibility notes."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from support_agent.domain.money import price_difference, round_gift_card_balance


class MoneyCompatibilityTests(unittest.TestCase):
    def test_published_midpoints_keep_python_float_rounding(self):
        for value, expected in ((1.125, 1.12), (1.375, 1.38), (-1.125, -1.12),
                                (2.675, 2.67), (10.005, 10.01)):
            with self.subTest(value=value):
                self.assertEqual(price_difference([(0.0, value)]), expected)

    def test_total_is_rounded_once_and_duplicate_pairs_are_preserved(self):
        self.assertEqual(price_difference([(0.0, 0.014), (0.0, 0.014)]), 0.03)
        # Per-pair rounding would incorrectly produce 0.02.

    def test_request_order_is_preserved_at_a_rounding_boundary(self):
        # Synthetic finite prices; sub-cent precision is not discarded.
        charge = (5.0, 105.0)
        refund = (105.0, 5.0)
        small_charge = (0.005, 0.01)
        self.assertEqual(price_difference([charge, refund, small_charge]), 0.01)
        self.assertEqual(price_difference([charge, small_charge, refund]), 0.00)

    def test_prices_keep_original_precision_and_refund_direction(self):
        self.assertEqual(price_difference([(1.001, 1.005)]), 0.00)
        self.assertEqual(price_difference([(20.0, 12.5)]), -7.50)
        self.assertEqual(price_difference(iter([(12.5, 20.0)])), 7.50)

    def test_empty_and_cancelled_estimates_are_zero(self):
        self.assertEqual(price_difference([]), 0.0)
        self.assertEqual(price_difference([(5, 8), (8, 5)]), 0.0)

    def test_updated_gift_card_balance_uses_published_rounding(self):
        for value, expected in ((1.125, 1.12), (2.675, 2.67), (10.005, 10.01),
                                (10, 10.0), (0, 0.0)):
            with self.subTest(value=value):
                self.assertEqual(round_gift_card_balance(value), expected)

    def test_non_json_and_nonfinite_numbers_are_rejected_not_defaulted(self):
        for value in (True, False, "2.675", None, Decimal("2.675"),
                      float("nan"), float("inf"), -float("inf")):
            expected = ValueError if type(value) is float else TypeError
            with self.subTest(value=repr(value)):
                with self.assertRaises(expected):
                    price_difference([(value, 1.0)])
                with self.assertRaises(expected):
                    price_difference([(1.0, value)])
                with self.assertRaises(expected):
                    round_gift_card_balance(value)

    def test_overflow_is_rejected_before_it_can_become_a_quote(self):
        with self.assertRaises(ValueError):
            price_difference([(-1e308, 1e308)])
        with self.assertRaises(ValueError):
            price_difference([(0.0, 1e308), (0.0, 1e308)])
        with self.assertRaises(ValueError):
            round_gift_card_balance(10 ** 400)


if __name__ == "__main__":
    unittest.main()
