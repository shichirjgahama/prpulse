"""Базовые классы метрик и контракт плагинов."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class MetricValue:
    scope: str  # project | module | file | entity
    target: str
    metric: str
    value: float
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "target": self.target,
            "metric": self.metric,
            "value": float(self.value),
            "extra": self.extra,
        }


class Metric:
    """Базовая метрика. Плагин обязан задать name и реализовать compute()."""

    name: str = "metric"
    version: str = "1.0"
    kind: str = "classic"  # classic | custom | series | plugin
    description: str = ""
    unit: str = ""
    formula: str = ""

    def compute(self, ctx) -> Sequence[MetricValue]:  # pragma: no cover - интерфейс
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "description": self.description,
            "unit": self.unit,
            "formula": self.formula,
        }
