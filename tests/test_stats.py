"""Тесты корреляций: ручные Пирсон и Спирмен, перестановочный p-value."""

from __future__ import annotations

import unittest

from projectpulse.analysis.stats import (
    correlate,
    interpret,
    pearson,
    permutation_pvalue,
    rankdata,
    spearman,
    zscores,
)


class CorrelationTests(unittest.TestCase):
    def test_pearson_exact_values(self) -> None:
        self.assertAlmostEqual(pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(pearson([1, 2, 3], [6, 4, 2]), -1.0)
        self.assertEqual(pearson([1, 1, 1], [1, 2, 3]), 0.0)
        self.assertEqual(pearson([1], [1]), 0.0)
        self.assertEqual(pearson([1, 2], [1]), 0.0)

    def test_rankdata_handles_ties(self) -> None:
        self.assertEqual(rankdata([10, 20, 20, 30]), [1.0, 2.5, 2.5, 4.0])
        self.assertEqual(rankdata([5]), [1.0])

    def test_spearman_monotonic(self) -> None:
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [1, 4, 9, 16]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [30, 20, 10]), -1.0)
        self.assertEqual(spearman([1, 1, 1], [1, 2, 3]), 0.0)

    def test_permutation_is_deterministic_and_bounded(self) -> None:
        x = [1, 2, 3, 4, 5, 6, 7, 8]
        y = [2, 1, 4, 3, 6, 5, 8, 7]
        first = permutation_pvalue(x, y, permutations=200, seed=42)
        second = permutation_pvalue(x, y, permutations=200, seed=42)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0.0)
        self.assertLessEqual(first, 1.0)
        self.assertEqual(permutation_pvalue([1, 2], [2, 1]), 1.0)

    def test_zscores(self) -> None:
        values = zscores([1, 2, 3])
        self.assertAlmostEqual(sum(values), 0.0, places=9)
        self.assertGreater(values[-1], 0)
        self.assertEqual(zscores([5, 5, 5]), [0.0, 0.0, 0.0])
        self.assertEqual(zscores([]), [])

    def test_correlate_and_interpret(self) -> None:
        result = correlate("test", list(range(10)), list(range(10)), permutations=100)
        payload = result.as_dict()
        self.assertEqual(payload["name"], "test")
        self.assertEqual(payload["n"], 10)
        self.assertAlmostEqual(payload["pearson"], 1.0)
        self.assertGreater(payload["p_value"], 0.0)
        self.assertLessEqual(payload["p_value"], 1.0)
        self.assertEqual(interpret(0.1), "очень слабая")
        self.assertEqual(interpret(0.9), "сильная")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
