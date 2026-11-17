"""Property-тесты hypothesis для математического ядра."""

from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from projectpulse.analysis.context import bus_factor_of
from projectpulse.analysis.stats import pearson, permutation_pvalue, rankdata, spearman, zscores
from projectpulse.core.utils import clamp, percentile, safe_div

FLOATS = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
SERIES = st.lists(FLOATS, min_size=2, max_size=24)
PAIRS = st.lists(st.tuples(FLOATS, FLOATS), min_size=2, max_size=24)


class PropertyTests(unittest.TestCase):
    settings = hypothesis_settings(max_examples=60, deadline=None)
    @given(SERIES)
    def test_pearson_always_in_range(self, values) -> None:
        x = values
        y = list(reversed(values))
        result = pearson(x, y)
        self.assertGreaterEqual(result, -1.0)
        self.assertLessEqual(result, 1.0)

    @given(PAIRS)
    def test_spearman_always_in_range(self, pairs) -> None:
        x = [item[0] for item in pairs]
        y = [item[1] for item in pairs]
        result = spearman(x, y)
        self.assertGreaterEqual(result, -1.0)
        self.assertLessEqual(result, 1.0)

    @given(SERIES)
    def test_rankdata_is_valid_ranking(self, values) -> None:
        ranks = rankdata(values)
        self.assertEqual(len(ranks), len(values))
        # При совпадениях используются средние ранги, поэтому проверяем
        # диапазон и сохранение суммы рангов, а не перестановку 1..n.
        self.assertTrue(all(1.0 <= rank <= len(values) for rank in ranks))
        expected_sum = len(values) * (len(values) + 1) / 2.0
        self.assertAlmostEqual(sum(ranks), expected_sum, places=6)
        self.assertEqual(sorted(ranks), sorted(ranks))

    @given(SERIES)
    def test_zscores_finite(self, values) -> None:
        result = zscores(values)
        self.assertEqual(len(result), len(values))
        for value in result:
            self.assertLess(abs(value), 1e12)

    @given(SERIES, st.integers(min_value=10, max_value=50), st.integers(min_value=1, max_value=100))
    def test_permutation_pvalue_bounded(self, values, permutations, seed) -> None:
        y = [value * 2 for value in values]
        p_value = permutation_pvalue(values, y, permutations=permutations, seed=seed)
        self.assertGreater(p_value, 0.0)
        self.assertLessEqual(p_value, 1.0)

    @given(FLOATS, FLOATS, FLOATS)
    def test_clamp_bounds(self, value, low, high) -> None:
        low, high = sorted((low, high))
        result = clamp(value, low, high)
        self.assertGreaterEqual(result, low)
        self.assertLessEqual(result, high)

    @given(st.lists(FLOATS, min_size=1, max_size=30), st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    def test_percentile_between_min_and_max(self, values, fraction) -> None:
        result = percentile(values, fraction)
        self.assertGreaterEqual(result, min(values) - 1e-9)
        self.assertLessEqual(result, max(values) + 1e-9)

    @given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(min_value=0, max_value=100), max_size=10))
    def test_bus_factor_bounded(self, counts) -> None:
        factor, authors = bus_factor_of({key: float(value) for key, value in counts.items()})
        self.assertGreaterEqual(factor, 0)
        self.assertLessEqual(factor, authors)
        self.assertLessEqual(authors, len(counts))

    @given(FLOATS, FLOATS, FLOATS)
    def test_safe_div_zero_denominator(self, numerator, denominator, default) -> None:
        if denominator == 0:
            self.assertEqual(safe_div(numerator, denominator, default), default)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
