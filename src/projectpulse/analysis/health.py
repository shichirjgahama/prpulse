"""Индекс здоровья проекта: 0..100 и вклад компонентов."""

from __future__ import annotations

from typing import Sequence

from projectpulse.analysis.rules.engine import severity_counts
from projectpulse.core.utils import clamp, is_support_path, percentile, safe_div


def _component(title: str, penalty: float, maximum: float, detail: str) -> dict:
    return {
        "title": title,
        "penalty": round(clamp(penalty, 0.0, maximum), 2),
        "max": maximum,
        "score": round(maximum - clamp(penalty, 0.0, maximum), 2),
        "detail": detail,
    }


def compute_health(findings: Sequence[dict], metrics, ctx) -> dict:
    counts = severity_counts(findings)
    risk_penalty = (
        counts.get("critical", 0) * 9.0
        + counts.get("warning", 0) * 4.5
        + counts.get("info", 0) * 1.5
    )
    risks = _component(
        "Риски правил",
        risk_penalty,
        45.0,
        f"критичных {counts.get('critical', 0)}, предупреждений {counts.get('warning', 0)}",
    )

    complexity = {
        path: value for path, value in metrics.files("complexity_max") if not is_support_path(path)
    }
    churn = {path: value for path, value in metrics.files("churn_90d") if not is_support_path(path)}
    p90_complexity = max(1.0, percentile(list(complexity.values()), 0.90))
    p90_churn = max(1.0, percentile(list(churn.values()), 0.90))
    file_risks: list[float] = []
    for path, value in complexity.items():
        complexity_factor = clamp(value / max(25.0, p90_complexity), 0.0, 1.0)
        churn_factor = clamp(churn.get(path, 0.0) / max(150.0, p90_churn), 0.0, 1.0)
        file_risks.append(complexity_factor * churn_factor)
    file_risks.sort(reverse=True)
    hotspot_penalty = sum(file_risks[:5]) * 6.0
    hotspots = _component(
        "Горячие точки",
        hotspot_penalty,
        25.0,
        f"сложность P90 {p90_complexity:.0f}, churn P90 {p90_churn:.0f}",
    )

    avg_share = metrics.get("avg_file_top_share")
    bus_factor = metrics.get("bus_factor")
    authors = metrics.get("bus_factor_authors")
    if authors <= 0:
        knowledge_penalty = 0.0
        knowledge_detail = "нет истории изменений"
    else:
        knowledge_penalty = 8.0 * avg_share + 12.0 * (1.0 - min(bus_factor, 4.0) / 4.0)
        knowledge_detail = f"средняя доля лидера {avg_share:.2f}, bus factor {bus_factor:.0f}"
    knowledge = _component("Концентрация знаний", knowledge_penalty, 20.0, knowledge_detail)

    cycles = metrics.get("cycle_count")
    volatile = metrics.get("api_volatile_files")
    god_modules = sum(1 for finding in findings if finding.get("rule") == "god_module")
    structure_penalty = cycles * 2.5 + volatile * 1.5 + god_modules * 2.5
    structure = _component(
        "Структура зависимостей",
        structure_penalty,
        10.0,
        f"циклов {cycles:.0f}, нестабильных API {volatile:.0f}, модулей-посредников {god_modules}",
    )

    components = {
        "risks": risks,
        "hotspots": hotspots,
        "knowledge": knowledge,
        "structure": structure,
    }
    penalty = sum(item["penalty"] for item in components.values())
    score = round(clamp(100.0 - penalty, 0.0, 100.0), 1)
    if score >= 80:
        label = "Хорошее состояние"
    elif score >= 60:
        label = "Умеренное состояние"
    elif score >= 40:
        label = "Повышенный риск"
    else:
        label = "Критическое состояние"
    return {
        "score": score,
        "label": label,
        "penalty": round(penalty, 2),
        "components": components,
        "counts": counts,
        "summary": (
            f"Индекс {score:.1f}/100: {label.lower()}. Снижение на {penalty:.1f} балла: "
            + ", ".join(f"{item['title'].lower()} -{item['penalty']:.1f}" for item in components.values())
        ),
    }
