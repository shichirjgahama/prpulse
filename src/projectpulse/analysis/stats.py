"""Корреляции Пирсона и Спирмена без scipy."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Sequence

from projectpulse.core.utils import mean


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    x_mean = mean([float(v) for v in x])
    y_mean = mean([float(v) for v in y])
    numerator = sum((float(a) - x_mean) * (float(b) - y_mean) for a, b in zip(x, y))
    denom_x = math.sqrt(sum((float(a) - x_mean) ** 2 for a in x))
    denom_y = math.sqrt(sum((float(b) - y_mean) ** 2 for b in y))
    if denom_x <= 1e-12 or denom_y <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, numerator / (denom_x * denom_y)))


def rankdata(values: Sequence[float]) -> list[float]:
    """Средние ранги при совпадениях (1-based)."""
    indexed = sorted((float(value), index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position
        while end + 1 < len(indexed) and abs(indexed[end + 1][0] - indexed[position][0]) < 1e-12:
            end += 1
        average_rank = (position + end) / 2.0 + 1.0
        for cursor in range(position, end + 1):
            ranks[indexed[cursor][1]] = average_rank
        position = end + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    return pearson(rankdata(x), rankdata(y))


def permutation_pvalue(
    x: Sequence[float],
    y: Sequence[float],
    statistic: Callable[[Sequence[float], Sequence[float]], float] = spearman,
    permutations: int = 1000,
    seed: int = 42,
) -> float:
    """Перестановочный p-value для |stat|, детерминированный seed."""
    if len(x) != len(y) or len(x) < 3:
        return 1.0
    observed = abs(statistic(x, y))
    rng = random.Random(seed)
    y_values = [float(v) for v in y]
    count = 0
    for _ in range(permutations):
        rng.shuffle(y_values)
        if abs(statistic(x, y_values)) >= observed - 1e-12:
            count += 1
    return (count + 1) / (permutations + 1)


def zscores(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    avg = mean([float(v) for v in values])
    variance = sum((float(v) - avg) ** 2 for v in values) / max(1, len(values) - 1)
    deviation = math.sqrt(variance)
    if deviation <= 1e-12:
        return [0.0 for _ in values]
    return [(float(v) - avg) / deviation for v in values]


@dataclass(frozen=True)
class CorrelationResult:
    name: str
    pearson: float
    spearman: float
    n: int
    p_value: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "pearson": round(self.pearson, 4),
            "spearman": round(self.spearman, 4),
            "n": self.n,
            "p_value": round(self.p_value, 4),
        }


def correlate(name: str, x: Sequence[float], y: Sequence[float], permutations: int = 500) -> CorrelationResult:
    return CorrelationResult(
        name=name,
        pearson=pearson(x, y),
        spearman=spearman(x, y),
        n=min(len(x), len(y)),
        p_value=permutation_pvalue(x, y, spearman, permutations=permutations),
    )


def interpret(value: float) -> str:
    magnitude = abs(value)
    if magnitude < 0.2:
        return "очень слабая"
    if magnitude < 0.4:
        return "слабая"
    if magnitude < 0.6:
        return "умеренная"
    if magnitude < 0.8:
        return "заметная"
    return "сильная"
