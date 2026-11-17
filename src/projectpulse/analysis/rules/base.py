"""Контракт правил риска."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class Finding:
    rule: str
    severity: str  # critical | warning | info
    target: str
    title: str
    explanation: str
    recommendation: str
    value: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "target": self.target,
            "title": self.title,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "value": self.value,
        }


class Rule:
    name: str = "rule"
    version: str = "1.0"
    description: str = ""
    trend: bool = False

    def evaluate(self, ctx, metrics) -> Sequence[Finding]:  # pragma: no cover - интерфейс
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "trend": self.trend,
        }
