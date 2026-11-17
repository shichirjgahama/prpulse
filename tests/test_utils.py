"""Тесты общих утилит."""

from __future__ import annotations

import unittest
from datetime import date

from projectpulse.core.utils import (
    clamp,
    entropy,
    format_duration_ms,
    human_bytes,
    is_support_module,
    is_support_path,
    mean,
    median,
    normalized_entropy,
    parse_date,
    percentage,
    percentile,
    recency_weight,
    round_value,
    safe_div,
    stable_id,
    stdev,
    truncate,
    week_key,
    week_start,
    weeks_between,
)


class UtilsTests(unittest.TestCase):
    def test_stable_id_is_deterministic(self) -> None:
        self.assertEqual(stable_id("a", 1), stable_id("a", 1))
        self.assertNotEqual(stable_id("a", 1), stable_id("a", 2))
        self.assertEqual(len(stable_id("x", length=8)), 8)

    def test_clamp_and_safe_div(self) -> None:
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)
        self.assertEqual(safe_div(4, 2), 2)
        self.assertEqual(safe_div(1, 0, default=-1), -1)

    def test_mean_median_percentile(self) -> None:
        self.assertAlmostEqual(mean([1, 2, 3]), 2.0)
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        self.assertAlmostEqual(percentile([0, 10], 0.5), 5.0)
        self.assertEqual(percentile([], 0.5), 0.0)
        self.assertEqual(percentile([7], 0.9), 7.0)

    def test_stdev_entropy(self) -> None:
        self.assertAlmostEqual(stdev([1, 2, 3]), 1.0)
        self.assertEqual(stdev([1]), 0.0)
        self.assertAlmostEqual(entropy([1, 1]), 1.0)
        self.assertAlmostEqual(normalized_entropy([1, 1]), 1.0)
        self.assertEqual(normalized_entropy([5]), 0.0)

    def test_week_helpers(self) -> None:
        # 2024-01-03 - среда, начало недели 2024-01-01.
        self.assertEqual(week_start(1704240000), date(2024, 1, 1))
        self.assertEqual(week_key(1704240000), "2024-01-01")
        weeks = weeks_between(date(2024, 1, 1), date(2024, 1, 15))
        self.assertEqual([item.isoformat() for item in weeks], ["2024-01-01", "2024-01-08", "2024-01-15"])
        self.assertEqual(weeks_between(date(2024, 1, 15), date(2024, 1, 1)), [])

    def test_support_paths(self) -> None:
        self.assertTrue(is_support_path("tests/test_core.py"))
        self.assertTrue(is_support_path("docs/examples/demo.py"))
        self.assertTrue(is_support_path("scripts/build.py"))
        self.assertTrue(is_support_path("pkg/conftest.py"))
        self.assertTrue(is_support_path("downstream/run.py"))
        self.assertFalse(is_support_path("src/pkg/core.py"))
        self.assertFalse(is_support_path("pkg/testing_utils.py"))
        self.assertTrue(is_support_module("docs"))
        self.assertTrue(is_support_module("Testing"))
        self.assertFalse(is_support_module("pkg"))

    def test_recency_weight(self) -> None:
        self.assertEqual(recency_weight(100, 100, 60), 1.0)
        self.assertLess(recency_weight(100, 100 + 60 * 86400, 60), 0.51)
        self.assertEqual(recency_weight(0, 10, 0), 1.0)

    def test_formatting_helpers(self) -> None:
        self.assertEqual(human_bytes(0), "0 Б")
        self.assertTrue(human_bytes(2048).endswith("КБ"))
        self.assertEqual(format_duration_ms(None), "-")
        self.assertEqual(format_duration_ms(900), "900 мс")
        self.assertTrue(format_duration_ms(2500).endswith("с"))
        self.assertEqual(percentage(0.5), "50.0%")
        self.assertEqual(round_value(0.00001), 0.0)
        self.assertEqual(truncate("a  b\nc", 10), "a b c")
        self.assertEqual(truncate("abc", 2), "a…")
        self.assertEqual(parse_date("2024-01-01"), date(2024, 1, 1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
