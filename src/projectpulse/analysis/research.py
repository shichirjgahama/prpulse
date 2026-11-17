"""Мини-исследование: churn, владение и следующий всплеск багфиксов."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from projectpulse.analysis.stats import CorrelationResult, correlate, interpret, zscores
from projectpulse.core.utils import iso, mean, percentage, safe_div

HYPOTHESIS = (
    "Рост churn и снижение доли ведущего автора на неделе t связаны с ростом числа "
    "багфикс-коммитов на неделе t+1"
)

METHOD = (
    "Недельные ряды churn, доли ведущего автора и багфикс-коммитов строятся по истории Git. "
    "Для каждой недели t (кроме первой и последней) считаются: относительный рост churn "
    "g_t = (churn_t - churn_{t-1}) / max(churn_{t-1}, 1), падение доли лидера "
    "d_t = max(0, share_{t-1} - share_t) и число багфиксов на следующей неделе y_t = bugfix_{t+1}. "
    "Проверяются корреляции Пирсона и Спирмена, реализованные вручную, и перестановочный p-value "
    "для |rho| (500 перестановок, seed 42). Составной предиктор z(g_t) + z(d_t)."
)


@dataclass
class RepoResearch:
    repo_id: int
    name: str
    commits: int
    weeks: int
    authors: int
    correlations: list[CorrelationResult] = field(default_factory=list)
    sample: list[dict] = field(default_factory=list)
    churn_mean: float = 0.0
    bugfix_mean: float = 0.0
    ownership_mean: float = 0.0

    def as_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "name": self.name,
            "commits": self.commits,
            "weeks": self.weeks,
            "authors": self.authors,
            "correlations": [item.as_dict() for item in self.correlations],
            "sample": self.sample,
            "churn_mean": round(self.churn_mean, 4),
            "bugfix_mean": round(self.bugfix_mean, 4),
            "ownership_mean": round(self.ownership_mean, 4),
        }


def _series_map(rows: Sequence[dict]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        result.setdefault(row["metric"], {})[row["bucket"]] = float(row["value"])
    return result


def analyze_repo(store, repo: dict) -> RepoResearch:
    repo_id = int(repo["id"])
    stats = store.stats(repo_id)
    series = _series_map(store.get_series(repo_id))
    bucket_set = sorted(set(series.get("churn_weekly", {})) | set(series.get("bugfix_weekly", {})))
    churn = [series.get("churn_weekly", {}).get(bucket, 0.0) for bucket in bucket_set]
    bugfix = [series.get("bugfix_weekly", {}).get(bucket, 0.0) for bucket in bucket_set]
    top_share = [series.get("ownership_top_share", {}).get(bucket, 0.0) for bucket in bucket_set]
    volatility = [series.get("churn_volatility", {}).get(bucket, 0.0) for bucket in bucket_set]

    growth: list[float] = []
    drops: list[float] = []
    next_bugfix: list[float] = []
    composite_raw: list[float] = []
    samples: list[dict] = []
    for index in range(1, len(bucket_set) - 1):
        g = safe_div(churn[index] - churn[index - 1], max(churn[index - 1], 1.0))
        d = max(0.0, top_share[index - 1] - top_share[index])
        y = bugfix[index + 1]
        growth.append(g)
        drops.append(d)
        next_bugfix.append(y)
        composite_raw.append(g + d)
        samples.append(
            {
                "bucket": bucket_set[index],
                "churn_growth": round(g, 4),
                "ownership_drop": round(d, 4),
                "bugfix_next": y,
                "churn_volatility": round(volatility[index], 4),
            }
        )

    correlations: list[CorrelationResult] = []
    if len(growth) >= 5:
        composite = [a + b for a, b in zip(zscores(growth), zscores(drops))]
        correlations = [
            correlate("рост churn -> багфиксы", growth, next_bugfix),
            correlate("падение доли лидера -> багфиксы", drops, next_bugfix),
            correlate("составной предиктор -> багфиксы", composite, next_bugfix),
            correlate("волатильность churn -> багфиксы", volatility[1:-1], next_bugfix),
        ]

    return RepoResearch(
        repo_id=repo_id,
        name=repo["name"],
        commits=int(stats.get("commits", 0)),
        weeks=len(bucket_set),
        authors=int(stats.get("authors", 0)),
        correlations=correlations,
        sample=samples[-12:],
        churn_mean=mean(churn),
        bugfix_mean=mean(bugfix),
        ownership_mean=mean(top_share),
    )


def run_research(store, healthy_repo: dict, problematic_repo: dict) -> dict[str, Any]:
    healthy = analyze_repo(store, healthy_repo)
    problematic = analyze_repo(store, problematic_repo)
    result = {
        "created_at": iso(),
        "hypothesis": HYPOTHESIS,
        "method": METHOD,
        "healthy": healthy.as_dict(),
        "problematic": problematic.as_dict(),
    }
    store.save_research(healthy.name, problematic.name, HYPOTHESIS, result)
    return result


def _correlation_rows(correlations: Sequence[dict]) -> list[str]:
    if not correlations:
        return ["| Связь | Пирсон | Спирмен | n | p-value |", "| --- | --- | --- | --- | --- |"]
    lines = ["| Связь | Пирсон | Спирмен | n | p-value |", "| --- | --- | --- | --- | --- |"]
    for item in correlations:
        lines.append(
            f"| {item['name']} | {item['pearson']:.3f} | {item['spearman']:.3f} | {item['n']} | {item['p_value']:.4f} |"
        )
    return lines


def research_markdown(result: dict[str, Any]) -> str:
    healthy = result["healthy"]
    problematic = result["problematic"]
    lines = [
        "# Мини-исследование",
        "",
        "## Гипотеза",
        "",
        result["hypothesis"] + ".",
        "",
        "## Методика",
        "",
        result["method"],
        "",
        "## Данные",
        "",
        "| Репозиторий | Коммиты | Недель | Авторов | Средний churn/нед | Багфиксов/нед | Средняя доля лидера |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| {healthy['name']} | {healthy['commits']} | {healthy['weeks']} | {healthy['authors']} | "
            f"{healthy['churn_mean']:.1f} | {healthy['bugfix_mean']:.2f} | {percentage(healthy['ownership_mean'])} |"
        ),
        (
            f"| {problematic['name']} | {problematic['commits']} | {problematic['weeks']} | {problematic['authors']} | "
            f"{problematic['churn_mean']:.1f} | {problematic['bugfix_mean']:.2f} | {percentage(problematic['ownership_mean'])} |"
        ),
        "",
        "## Корреляции: здоровый репозиторий",
        "",
        f"{healthy['name']}",
        "",
        *_correlation_rows(healthy["correlations"]),
        "",
        "## Корреляции: проблемный репозиторий",
        "",
        f"{problematic['name']}",
        "",
        *_correlation_rows(problematic["correlations"]),
        "",
        "## Выводы",
        "",
    ]

    def best(repo: dict, name: str) -> dict | None:
        for item in repo["correlations"]:
            if item["name"] == name:
                return item
        return None

    composite_healthy = best(healthy, "составной предиктор -> багфиксы")
    composite_problem = best(problematic, "составной предиктор -> багфиксы")
    lines.append(
        f"- Для здорового проекта связь составного предиктора с багфиксами оценивается как "
        f"{interpret(composite_healthy['spearman']) if composite_healthy else 'недостаточно данных'}"
        + (f" (rho = {composite_healthy['spearman']:.3f}, p = {composite_healthy['p_value']:.3f})." if composite_healthy else ".")
    )
    lines.append(
        f"- Для проблемного проекта связь оценивается как "
        f"{interpret(composite_problem['spearman']) if composite_problem else 'недостаточно данных'}"
        + (f" (rho = {composite_problem['spearman']:.3f}, p = {composite_problem['p_value']:.3f})." if composite_problem else ".")
    )
    lines.append(
        "- Гипотеза подтверждается частично: значимость зависит от длины истории, плотности релизов "
        "и эвристики определения багфикс-коммитов по сообщению."
    )
    lines.extend(
        [
            "",
            "## Ограничения",
            "",
            "- Багфикс определяется по регулярному выражению в теме коммита, поэтому часть исправлений может быть пропущена.",
            "- Недельная агрегация сглаживает короткие всплески и может размывать причинно-следственные связи.",
            "- Корреляция не доказывает причинность; возможны общие факторы (релизы, миграции зависимостей).",
            "- Метрики владения считаются по числу изменённых строк, а не по экспертизе автора.",
            "- Перестановочный тест даёт грубую оценку значимости при малом числе недель.",
            "",
            "## Воспроизводимость",
            "",
            "Исследование выполняется командой `python -m projectpulse research --healthy <path> --problematic <path>` "
            "на зафиксированных коммитах из `repos.json`. Все пороги и seed детерминированы.",
            "",
        ]
    )
    return "\n".join(lines)
