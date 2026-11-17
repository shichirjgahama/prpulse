"""Сравнение двух репозиториев по пяти ключевым показателям."""

from __future__ import annotations

from typing import Any

from projectpulse.core.utils import safe_div


INDICATORS = [
    ("health", "Индекс здоровья", "баллы 0..100", True, "health", ""),
    ("complexity", "Средняя сложность функции", "баллы", False, "metric", "avg_function_complexity"),
    ("churn", "Плотность churn за 90 дней", "строк на 100 LOC", False, "metric", "churn_density_90d"),
    ("bugfix", "Доля багфикс-коммитов", "%", False, "metric", "bugfix_share"),
    ("bus_factor", "Bus factor проекта", "авторы", True, "metric", "bus_factor"),
]


def _latest(store, repo_id: int) -> tuple[dict | None, dict | None, dict]:
    run = store.latest_run(repo_id)
    if not run:
        return None, None, {}
    run_id = int(run["id"])
    health = store.get_health(run_id)
    metrics = store.metric_map(run_id)
    return run, health, metrics


def compare_repos(store, repo_a: dict, repo_b: dict) -> dict[str, Any]:
    run_a, health_a, metrics_a = _latest(store, int(repo_a["id"]))
    run_b, health_b, metrics_b = _latest(store, int(repo_b["id"]))
    if not run_a or not run_b:
        raise ValueError("Для сравнения нужны успешные импорты обоих репозиториев")

    rows: list[dict] = []
    wins_a = wins_b = 0
    for key, title, unit, higher_better, source, metric in INDICATORS:
        if source == "health":
            value_a = float(health_a["score"]) if health_a else 0.0
            value_b = float(health_b["score"]) if health_b else 0.0
        else:
            value_a = float(metrics_a.get(("project", "project", metric), 0.0))
            value_b = float(metrics_b.get(("project", "project", metric), 0.0))
        if key == "bugfix":
            display_a = value_a * 100
            display_b = value_b * 100
        else:
            display_a = value_a
            display_b = value_b
        if abs(value_a - value_b) < 1e-9:
            better = "tie"
        elif (value_a > value_b) == higher_better:
            better = "a"
            wins_a += 1
        else:
            better = "b"
            wins_b += 1
        rows.append(
            {
                "key": key,
                "title": title,
                "unit": unit,
                "a": display_a,
                "b": display_b,
                "higher_better": higher_better,
                "better": better,
                "delta": display_a - display_b,
            }
        )

    if wins_a > wins_b:
        verdict = f"Лучше выглядит {repo_a['name']}: побед {wins_a} из {len(INDICATORS)}"
    elif wins_b > wins_a:
        verdict = f"Лучше выглядит {repo_b['name']}: побед {wins_b} из {len(INDICATORS)}"
    else:
        verdict = "Репозитории сопоставимы по выбранным показателям"

    return {
        "a": {
            "id": int(repo_a["id"]),
            "name": repo_a["name"],
            "run_id": int(run_a["id"]),
            "health": float(health_a["score"]) if health_a else 0.0,
            "score_label": (health_a or {}).get("components", {}).get("label", ""),
        },
        "b": {
            "id": int(repo_b["id"]),
            "name": repo_b["name"],
            "run_id": int(run_b["id"]),
            "health": float(health_b["score"]) if health_b else 0.0,
            "score_label": (health_b or {}).get("components", {}).get("label", ""),
        },
        "indicators": rows,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "verdict": verdict,
    }


def indicator_delta(row: dict) -> str:
    delta = row["delta"]
    if abs(delta) < 1e-9:
        return "0"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2f}"


def relative_gap(row: dict) -> float:
    return safe_div(abs(row["a"] - row["b"]), max(abs(row["a"]), abs(row["b"]), 1e-9))
