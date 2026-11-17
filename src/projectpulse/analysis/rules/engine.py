"""Запуск правил и нормализация результатов."""

from __future__ import annotations

import logging
from typing import Sequence

from projectpulse.analysis.rules.base import Finding

logger = logging.getLogger("projectpulse.rules")
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
SEVERITY_TITLES = {"critical": "Критично", "warning": "Предупреждение", "info": "Информация"}


def evaluate_rules(rules: Sequence, ctx, metrics, log: logging.Logger | None = None) -> list[dict]:
    findings: list[Finding] = []
    for rule in rules:
        try:
            produced = rule.evaluate(ctx, metrics)
        except Exception as exc:  # noqa: BLE001 - плагин не должен ломать анализ
            (log or logger).exception("Правило %s завершилось ошибкой: %s", getattr(rule, "name", "?"), exc)
            continue
        for finding in produced:
            if finding.severity not in SEVERITY_ORDER:
                finding.severity = "warning"
            findings.append(finding)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule, f.target))
    return [finding.as_dict() for finding in findings]


def severity_counts(findings: Sequence[dict]) -> dict[str, int]:
    result = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        result[severity] = result.get(severity, 0) + 1
    return result
