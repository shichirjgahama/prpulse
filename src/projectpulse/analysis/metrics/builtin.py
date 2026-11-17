"""Встроенные метрики: 5 классических, 3 собственные, 2 временных ряда."""

from __future__ import annotations

import math
from collections import defaultdict

from projectpulse.analysis.anomalies import zscore_anomalies
from projectpulse.analysis.context import module_name
from projectpulse.analysis.metrics.base import Metric, MetricValue
from projectpulse.core.utils import is_support_path, mean, percentile, safe_div


def _path_rows(ctx) -> list[str]:
    return sorted(ctx.files_by_path)


class LocMetric(Metric):
    name = "loc"
    kind = "classic"
    description = "Физические строки, строки кода, комментарии и плотность комментариев"
    unit = "строки"
    formula = "LOC = число строк; SLOC = строки с кодом; comment_density = comments / (SLOC + comments)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        total_loc = total_sloc = total_comments = 0
        for path in _path_rows(ctx):
            file = ctx.files_by_path[path]
            loc = int(file.get("loc", 0))
            sloc = int(file.get("sloc", 0))
            comments = int(file.get("comments", 0))
            total_loc += loc
            total_sloc += sloc
            total_comments += comments
            values.append(MetricValue("file", path, "loc", loc))
            values.append(MetricValue("file", path, "sloc", sloc))
            values.append(MetricValue("file", path, "comments", comments))
        values.append(MetricValue("project", "project", "loc", total_loc))
        values.append(MetricValue("project", "project", "sloc", total_sloc))
        values.append(MetricValue("project", "project", "comments", total_comments))
        values.append(
            MetricValue(
                "project",
                "project",
                "comment_density",
                safe_div(total_comments, total_sloc + total_comments),
            )
        )
        files_count = len(ctx.files_by_path)
        values.append(MetricValue("project", "project", "files", files_count))
        values.append(
            MetricValue("project", "project", "avg_file_loc", safe_div(total_loc, files_count))
        )
        return values


class ComplexityMetric(Metric):
    name = "complexity"
    kind = "classic"
    description = "Цикломатическая сложность Маккейба по AST (без вложенных функций)"
    unit = "баллы"
    formula = "M = 1 + число решений (if/for/while/except/boolop/comprehension-if/match-case)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        total_complexity = 0
        max_complexity = 0
        functions = 0
        complex_functions = 0
        function_values: list[float] = [
            float(entity.get("complexity", 0))
            for entity in ctx.entities
            if entity.get("kind") == "function"
        ]
        for path in _path_rows(ctx):
            file = ctx.files_by_path[path]
            file_total = int(file.get("complexity_total", 0))
            file_max = int(file.get("complexity_max", 0))
            file_functions = int(file.get("functions", 0))
            total_complexity += file_total
            max_complexity = max(max_complexity, file_max)
            functions += file_functions
            values.append(MetricValue("file", path, "complexity_total", file_total))
            values.append(MetricValue("file", path, "complexity_max", file_max))
            values.append(
                MetricValue("file", path, "avg_function_complexity", safe_div(file_total, file_functions))
            )
        for entity in sorted(ctx.entities, key=lambda e: (-int(e.get("complexity", 0)), e["path"], e["qualname"])):
            complexity = int(entity.get("complexity", 0))
            if entity.get("kind") != "function" or complexity < 8:
                continue
            values.append(
                MetricValue(
                    "entity",
                    entity["qualname"],
                    "complexity",
                    complexity,
                    {"path": entity["path"], "lineno": entity.get("lineno", 0)},
                )
            )
        for entity in ctx.entities:
            if entity.get("kind") == "function":
                complex_functions += 1 if int(entity.get("complexity", 0)) >= 10 else 0
        values.append(MetricValue("project", "project", "complexity_total", total_complexity))
        values.append(MetricValue("project", "project", "complexity_max", max_complexity))
        values.append(
            MetricValue("project", "project", "avg_function_complexity", safe_div(total_complexity, functions))
        )
        values.append(
            MetricValue("project", "project", "p90_function_complexity", percentile(function_values, 0.90))
        )
        values.append(MetricValue("project", "project", "complex_functions", complex_functions))
        return values


class ChurnMetric(Metric):
    name = "churn"
    kind = "classic"
    description = "Churn: сумма добавленных и удалённых строк, свежесть и плотность изменений"
    unit = "строки"
    formula = "churn = additions + deletions; density_90d = churn_90d / LOC * 100"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        total_recent = 0
        total_churn = 0
        total_commits = 0
        total_bugfix = 0
        for path in _path_rows(ctx):
            stats = ctx.path_stats.get(path)
            file = ctx.files_by_path[path]
            loc = int(file.get("loc", 0))
            churn_total = stats.churn_total if stats else 0
            churn_recent = stats.churn_recent if stats else 0
            commits = len(stats.commits) if stats else 0
            bugfix = len(stats.bugfix_commits) if stats else 0
            total_recent += churn_recent
            total_churn += churn_total
            total_commits += commits
            total_bugfix += bugfix
            values.append(MetricValue("file", path, "churn_total", churn_total))
            values.append(MetricValue("file", path, "churn_90d", churn_recent))
            values.append(
                MetricValue("file", path, "churn_density_90d", safe_div(churn_recent, max(loc, 1)) * 100)
            )
            values.append(MetricValue("file", path, "commit_count", commits))
            values.append(MetricValue("file", path, "bugfix_commits", bugfix))
        commits_total = len(ctx.commits)
        bugfix_commits = sum(1 for commit in ctx.commits if int(commit.get("is_bugfix", 0)))
        values.append(MetricValue("project", "project", "churn_total", total_churn))
        values.append(MetricValue("project", "project", "churn_90d", total_recent))
        values.append(
            MetricValue(
                "project",
                "project",
                "churn_density_90d",
                safe_div(total_recent, max(ctx.total_loc(), 1)) * 100,
            )
        )
        values.append(MetricValue("project", "project", "commits", commits_total))
        values.append(MetricValue("project", "project", "churn_per_commit", safe_div(total_churn, commits_total)))
        values.append(MetricValue("project", "project", "bugfix_share", safe_div(bugfix_commits, commits_total)))
        values.append(MetricValue("project", "project", "bugfix_commits", bugfix_commits))
        return values


class OwnershipMetric(Metric):
    name = "ownership"
    kind = "classic"
    description = "Концентрация знаний: доля ведущего автора и нормированная энтропия"
    unit = "доля"
    formula = "top_share = max(author_changes) / sum(author_changes); H_norm = H / log2(authors)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        product_shares: list[float] = []
        single_owner = 0
        for path in _path_rows(ctx):
            stats = ctx.path_stats.get(path)
            top_share = stats.top_share if stats else 0.0
            entropy = stats.ownership_entropy if stats else 0.0
            authors = len(stats.authors) if stats else 0
            if not is_support_path(path):
                product_shares.append(top_share)
            if (
                stats is not None
                and authors <= 1
                and len(stats.commits) >= 1
                and not is_support_path(path)
            ):
                single_owner += 1
            values.append(MetricValue("file", path, "ownership_top_share", top_share))
            values.append(MetricValue("file", path, "ownership_entropy", entropy))
            values.append(MetricValue("file", path, "ownership_authors_count", authors))

        for module, data in sorted(ctx.module_ownership().items()):
            values.append(MetricValue("module", module, "ownership_top_share", data["top_share"]))
            values.append(MetricValue("module", module, "ownership_entropy", data["entropy"]))
            values.append(
                MetricValue("module", module, "ownership_authors_count", data["authors_count"])
            )

        project = ctx.project_ownership
        values.append(MetricValue("project", "project", "ownership_top_share", project["top_share"]))
        values.append(MetricValue("project", "project", "ownership_entropy", project["entropy"]))
        values.append(
            MetricValue("project", "project", "ownership_authors_count", project["authors_count"])
        )
        values.append(MetricValue("project", "project", "single_owner_files", single_owner))
        values.append(MetricValue("project", "project", "avg_file_top_share", mean(product_shares)))
        return values


class BusFactorMetric(Metric):
    name = "bus_factor"
    kind = "classic"
    description = "Bus factor: минимум авторов, покрывающих 50% изменений"
    unit = "авторы"
    formula = "BF = min k, при котором сумма k крупнейших вкладов >= 0.5 * сумма всех вкладов"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        for module, data in sorted(ctx.module_ownership().items()):
            values.append(MetricValue("module", module, "bus_factor", data["bus_factor"]))
            values.append(MetricValue("module", module, "bus_factor_authors", data["authors_count"]))
            values.append(MetricValue("module", module, "module_commits", data["commits"]))
        project = ctx.project_ownership
        values.append(MetricValue("project", "project", "bus_factor", project["bus_factor"]))
        values.append(MetricValue("project", "project", "bus_factor_authors", project["authors_count"]))
        values.append(MetricValue("project", "project", "bus_factor_commits", project["commits"]))
        return values


class FixPressureMetric(Metric):
    name = "fix_pressure"
    kind = "custom"
    description = "Fix Pressure Index: доля багфикс-коммитов с экспоненциальным весом свежести"
    unit = "доля"
    formula = "FPI = sum(w_t * is_bugfix) / sum(w_t), w_t = 0.5 ^ (age_days / 60)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        recent_total_weight = 0.0
        recent_bugfix_weight = 0.0
        baseline_total_weight = 0.0
        baseline_bugfix_weight = 0.0
        for path in _path_rows(ctx):
            stats = ctx.path_stats.get(path)
            if stats is None:
                continue
            recent = safe_div(stats.recent_fix_weight_bugfix, stats.recent_fix_weight_total)
            baseline = safe_div(stats.baseline_fix_weight_bugfix, stats.baseline_fix_weight_total)
            values.append(MetricValue("file", path, "fix_pressure", stats.fix_pressure))
            values.append(MetricValue("file", path, "fix_pressure_recent", recent))
            values.append(MetricValue("file", path, "fix_pressure_previous", baseline))
            values.append(
                MetricValue(
                    "file",
                    path,
                    "fix_pressure_growth",
                    safe_div(recent - baseline, max(baseline, 1e-9)),
                )
            )
            values.append(MetricValue("file", path, "bugfix_commits", len(stats.bugfix_commits)))
            if is_support_path(path):
                continue
            recent_total_weight += stats.recent_fix_weight_total
            recent_bugfix_weight += stats.recent_fix_weight_bugfix
            baseline_total_weight += stats.baseline_fix_weight_total
            baseline_bugfix_weight += stats.baseline_fix_weight_bugfix
        recent_project = safe_div(recent_bugfix_weight, recent_total_weight)
        baseline_project = safe_div(baseline_bugfix_weight, baseline_total_weight)
        values.append(MetricValue("project", "project", "fix_pressure", recent_project))
        values.append(MetricValue("project", "project", "fix_pressure_recent", recent_project))
        values.append(MetricValue("project", "project", "fix_pressure_previous", baseline_project))
        values.append(
            MetricValue(
                "project",
                "project",
                "fix_pressure_growth",
                safe_div(recent_project - baseline_project, max(baseline_project, 1e-9)),
            )
        )
        return values


class CouplingPressureMetric(Metric):
    name = "coupling_pressure"
    kind = "custom"
    description = "Coupling Pressure: давление связей на 1000 строк с штрафом за циклы"
    unit = "связи/1000 LOC"
    formula = "CP = (fan_in + 0.5 * fan_out) * (1 + 0.5 * in_cycle) * 1000 / max(LOC, 50)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        graph = ctx.file_graph
        cycle_nodes: set[str] = set()
        product_cycles = [
            component for component in graph.cycles() if not any(is_support_path(path) for path in component)
        ]
        for component in product_cycles:
            cycle_nodes.update(component)
        per_file: list[float] = []
        module_values: dict[str, list[float]] = defaultdict(list)
        for path in _path_rows(ctx):
            loc = int(ctx.files_by_path[path].get("loc", 0))
            fan_in = graph.fan_in(path)
            fan_out = graph.fan_out(path)
            in_cycle = path in cycle_nodes
            pressure = (
                (fan_in + 0.5 * fan_out)
                * (1.0 + 0.5 * (1 if in_cycle else 0))
                * 1000.0
                / max(loc, 50)
            )
            per_file.append(pressure)
            module_values[module_name(path)].append(pressure)
            values.append(MetricValue("file", path, "fan_in", fan_in))
            values.append(MetricValue("file", path, "fan_out", fan_out))
            values.append(MetricValue("file", path, "in_cycle", 1.0 if in_cycle else 0.0))
            values.append(MetricValue("file", path, "coupling_pressure", pressure))
        for module, pressures in sorted(module_values.items()):
            values.append(MetricValue("module", module, "coupling_pressure", mean(pressures)))
        values.append(MetricValue("project", "project", "coupling_pressure_avg", mean(per_file)))
        values.append(MetricValue("project", "project", "coupling_pressure_max", max(per_file, default=0.0)))
        values.append(MetricValue("project", "project", "cycle_count", len(product_cycles)))
        return values


class InterfaceVolatilityMetric(Metric):
    name = "interface_volatility"
    kind = "custom"
    description = "Interface Volatility Index: как часто меняются публичные def/class"
    unit = "доля"
    formula = "IVI = sum(w_t * public_api_changed_t) / sum(w_t), w_t = 0.5 ^ (age_days / 180)"

    def compute(self, ctx) -> list[MetricValue]:
        values: list[MetricValue] = []
        weighted_sum = 0.0
        weighted_count = 0.0
        volatile_files = 0
        for path in _path_rows(ctx):
            data = ctx.history_metrics.get(path, {})
            computed = bool(data.get("commits_considered"))
            value = float(data.get("value", 0.0))
            changes = int(data.get("public_change_commits", 0))
            considered = int(data.get("commits_considered", 0))
            if computed:
                if not is_support_path(path):
                    weighted_sum += value * considered
                    weighted_count += considered
                if (
                    value >= ctx.thresholds.api_volatility_threshold
                    and changes >= ctx.thresholds.api_min_public_changes
                    and not is_support_path(path)
                ):
                    volatile_files += 1
            values.append(
                MetricValue(
                    "file",
                    path,
                    "interface_volatility",
                    value,
                    {"computed": computed, "public_change_commits": changes, "commits_considered": considered},
                )
            )
            values.append(MetricValue("file", path, "api_change_commits", changes))
        values.append(
            MetricValue("project", "project", "interface_volatility", safe_div(weighted_sum, weighted_count))
        )
        values.append(MetricValue("project", "project", "api_volatile_files", volatile_files))
        return values


class ChurnVolatilityMetric(Metric):
    name = "churn_volatility"
    kind = "series"
    description = "Временной ряд: коэффициент вариации недельного churn (окно 8 недель)"
    unit = "коэффициент"
    formula = "CV_t = stdev(churn[t-7..t]) / mean(churn[t-7..t])"

    def compute(self, ctx) -> list[MetricValue]:
        values = [float(row["value"]) for row in ctx.series.get("churn_volatility", [])]
        recent = values[-4:]
        previous = values[-8:-4]
        spikes = zscore_anomalies(
            [float(row["value"]) for row in ctx.series.get("churn_weekly", [])],
            threshold=ctx.thresholds.churn_spike_z,
        )
        return [
            MetricValue("project", "project", "churn_volatility", values[-1] if values else 0.0),
            MetricValue("project", "project", "churn_volatility_recent", mean(recent)),
            MetricValue("project", "project", "churn_volatility_previous", mean(previous)),
            MetricValue("project", "project", "churn_volatility_max", max(values, default=0.0)),
            MetricValue("project", "project", "churn_spike_count", len(spikes)),
        ]


class OwnershipDriftMetric(Metric):
    name = "ownership_drift"
    kind = "series"
    description = "Временной ряд: смещение доли ведущего автора между 4-недельными окнами"
    unit = "доля"
    formula = "OD_t = |top_share(window t-3..t) - top_share(window t-7..t-4)|"

    def compute(self, ctx) -> list[MetricValue]:
        values = [float(row["value"]) for row in ctx.series.get("ownership_drift", [])]
        shares = [float(row["value"]) for row in ctx.series.get("ownership_top_share", [])]
        return [
            MetricValue("project", "project", "ownership_drift", values[-1] if values else 0.0),
            MetricValue("project", "project", "ownership_drift_avg", mean(values[-12:])),
            MetricValue("project", "project", "ownership_drift_max", max(values, default=0.0)),
            MetricValue(
                "project", "project", "ownership_top_share_current", shares[-1] if shares else 0.0
            ),
        ]


def default_metrics() -> list[Metric]:
    return [
        LocMetric(),
        ComplexityMetric(),
        ChurnMetric(),
        OwnershipMetric(),
        BusFactorMetric(),
        FixPressureMetric(),
        CouplingPressureMetric(),
        InterfaceVolatilityMetric(),
        ChurnVolatilityMetric(),
        OwnershipDriftMetric(),
    ]


def register_default_metrics(registry) -> None:
    for metric in default_metrics():
        registry.register(metric, source="builtin")


def compute_metrics(metrics, ctx, logger=None) -> list[dict]:
    rows: list[dict] = []
    for metric in metrics:
        try:
            produced = metric.compute(ctx)
        except Exception as exc:  # noqa: BLE001 - плагин не должен ломать импорт
            if logger:
                logger.exception("Метрика %s завершилась ошибкой: %s", getattr(metric, "name", "?"), exc)
            continue
        for value in produced:
            rows.append(value.as_dict())
    rows.sort(key=lambda row: (row["metric"], row["scope"], row["target"], row["value"]))
    return rows
