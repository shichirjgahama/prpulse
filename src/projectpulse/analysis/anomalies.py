"""Детектор аномалий и вспомогательная статистика для трендов."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from projectpulse.core.utils import mean, stdev


@dataclass(frozen=True)
class Anomaly:
    index: int
    value: float
    z: float
    baseline_mean: float
    baseline_std: float


def zscore_anomalies(
    values: Sequence[float],
    window: int = 12,
    threshold: float = 2.5,
    min_periods: int = 4,
) -> list[Anomaly]:
    """Всплески относительно предыдущего окна (сам элемент не входит в базу)."""
    result: list[Anomaly] = []
    for index in range(min_periods, len(values)):
        start = max(0, index - window)
        baseline = [float(v) for v in values[start:index]]
        if len(baseline) < min_periods:
            continue
        avg = mean(baseline)
        deviation = stdev(baseline)
        if deviation <= 1e-9:
            continue
        z = (float(values[index]) - avg) / deviation
        if z >= threshold:
            result.append(Anomaly(index=index, value=float(values[index]), z=z, baseline_mean=avg, baseline_std=deviation))
    return result


def linear_slope(values: Sequence[float]) -> float:
    """МНК-наклон по индексам 0..n-1 (в единицах значения за шаг)."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = mean([float(v) for v in values])
    numerator = sum((i - x_mean) * (float(v) - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


def mean_shift(values: Sequence[float], split: int, min_side: int = 3) -> float:
    """Разница средних до и после точки split, нормированная на общий разброс."""
    if split < min_side or len(values) - split < min_side:
        return 0.0
    before = [float(v) for v in values[:split]]
    after = [float(v) for v in values[split:]]
    deviation = stdev([float(v) for v in values])
    if deviation <= 1e-9:
        return 0.0
    return (mean(after) - mean(before)) / deviation


def best_change_point(values: Sequence[float], min_side: int = 3) -> tuple[int | None, float]:
    best_index: int | None = None
    best_score = 0.0
    for split in range(min_side, len(values) - min_side + 1):
        score = abs(mean_shift(values, split, min_side=min_side))
        if score > best_score:
            best_index = split
            best_score = score
    return best_index, best_score


def coefficient_of_variation(values: Sequence[float]) -> float:
    values = [float(v) for v in values]
    if not values:
        return 0.0
    avg = mean(values)
    if avg <= 0:
        return 0.0
    return stdev(values) / avg


def growth_rate(recent: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0 if recent <= 0 else 1.0
    return (recent - baseline) / baseline


def is_spike(values: Sequence[float], threshold: float = 2.5) -> bool:
    return bool(zscore_anomalies(values, threshold=threshold))
