"""Пример плагина ProjectPulse: плотность TODO и правило их скопления.

Плагин демонстрирует контракт расширения: классы METRICS и RULES создаются
автоматически, а функция register() получает контейнер сервисов.
"""

from __future__ import annotations

from projectpulse.analysis.metrics.base import Metric, MetricValue
from projectpulse.analysis.rules.base import Finding, Rule
from projectpulse.core.utils import is_support_path


class TodoDensityMetric(Metric):
    name = "todo_density"
    version = "1.0"
    kind = "plugin"
    description = "Число TODO/FIXME на 1000 строк кода"
    unit = "на 1000 LOC"
    formula = "TD = todo_count / max(loc, 1) * 1000"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        total_todos = 0
        total_loc = 0
        for path, row in sorted(ctx.files_by_path.items()):
            todos = int(row.get("todo_count", 0))
            loc = int(row.get("loc", 0))
            total_todos += todos
            total_loc += loc
            values.append(MetricValue("file", path, self.name, todos / max(loc, 1) * 1000.0))
        values.append(MetricValue("project", "project", self.name, total_todos / max(total_loc, 1) * 1000.0))
        return values


class TodoClusterRule(Rule):
    name = "todo_cluster"
    version = "1.0"
    description = "В файле накопилось три и более отметок TODO/FIXME"
    trend = False

    def evaluate(self, ctx, metrics) -> list[Finding]:
        findings: list[Finding] = []
        rows = sorted(
            (
                (int(row.get("todo_count", 0)), path)
                for path, row in ctx.files_by_path.items()
                if int(row.get("todo_count", 0)) >= 3 and not is_support_path(path)
            ),
            reverse=True,
        )
        for count, path in rows[:10]:
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning" if count >= 5 else "info",
                    target=path,
                    title="Скопление TODO/FIXME",
                    explanation=f"В файле {count} незавершённых отметок, это повышает риск забытых решений.",
                    recommendation="Разобрать отметки, преобразовать в задачи и указать владельца.",
                    value={"todo_count": count},
                )
            )
        return findings


METRICS = [TodoDensityMetric]
RULES = [TodoClusterRule]


def register(container) -> None:
    container.register("example_todo_plugin", "1.0")
