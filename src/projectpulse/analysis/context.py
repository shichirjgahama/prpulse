"""Контекст анализа: агрегаты по истории, владению, недельные ряды."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from projectpulse.analysis.graph import DependencyGraph
from projectpulse.core.config import Thresholds
from projectpulse.core.utils import (
    is_support_path,
    mean,
    normalized_entropy,
    percentile,
    recency_weight,
    safe_div,
    week_key,
    week_start,
    weeks_between,
)


def bus_factor_of(counts: dict[str, float], coverage: float = 0.5) -> tuple[int, int]:
    """Минимум авторов, покрывающих долю coverage; возвращает (bf, всего авторов)."""
    positive = {author: float(value) for author, value in counts.items() if value > 0}
    total_authors = len(positive)
    if not positive:
        return 0, 0
    total = sum(positive.values())
    needed = total * coverage
    cumulative = 0.0
    for index, value in enumerate(sorted(positive.values(), reverse=True), start=1):
        cumulative += value
        if cumulative >= needed:
            return index, total_authors
    return total_authors, total_authors


def module_name(path: str) -> str:
    clean = path.replace("\\", "/")
    parts = clean.split("/")
    if len(parts) > 1 and parts[0] in {"src", "lib", "app"}:
        parts = parts[1:]
    if len(parts) <= 1:
        return "(root)"
    return parts[0]


@dataclass
class PathStats:
    commits: set[str] = field(default_factory=set)
    authors: dict[str, float] = field(default_factory=dict)
    additions: int = 0
    deletions: int = 0
    bugfix_commits: set[str] = field(default_factory=set)
    last_ts: int = 0
    churn_recent: int = 0
    fix_weight_total: float = 0.0
    fix_weight_bugfix: float = 0.0
    recent_fix_weight_total: float = 0.0
    recent_fix_weight_bugfix: float = 0.0
    baseline_fix_weight_total: float = 0.0
    baseline_fix_weight_bugfix: float = 0.0

    @property
    def churn_total(self) -> int:
        return self.additions + self.deletions

    @property
    def top_share(self) -> float:
        total = sum(self.authors.values())
        return safe_div(max(self.authors.values(), default=0.0), total)

    @property
    def ownership_entropy(self) -> float:
        return normalized_entropy(self.authors.values())

    @property
    def fix_pressure(self) -> float:
        return safe_div(self.fix_weight_bugfix, self.fix_weight_total)


@dataclass
class RepoContext:
    repo: dict
    as_of: int
    files: list[dict]
    commits: list[dict]
    commit_files: list[dict]
    entities: list[dict]
    refs: list[dict]
    imports: list[dict]
    file_graph: DependencyGraph
    entity_graph: DependencyGraph
    thresholds: Thresholds
    history_metrics: dict[str, dict] = field(default_factory=dict)
    config: object | None = None

    files_by_path: dict[str, dict] = field(init=False, default_factory=dict)
    commits_by_sha: dict[str, dict] = field(init=False, default_factory=dict)
    path_stats: dict[str, PathStats] = field(init=False, default_factory=dict)
    modules: dict[str, list[str]] = field(init=False, default_factory=dict)
    series: dict[str, list[dict]] = field(init=False, default_factory=dict)
    weekly: list[dict] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.files_by_path = {row["path"]: row for row in self.files}
        self.commits_by_sha = {row["sha"]: row for row in self.commits}
        self.modules = defaultdict(list)
        for path in self.files_by_path:
            self.modules[module_name(path)].append(path)
        self.modules = {key: sorted(value) for key, value in sorted(self.modules.items())}
        self._build_path_stats()
        self._build_series()

    # ------------------------------------------------------------------ base
    def _build_path_stats(self) -> None:
        stats: dict[str, PathStats] = defaultdict(PathStats)
        recent_start = self.as_of - self.thresholds.churn_recent_days * 86400
        for change in self.commit_files:
            commit = self.commits_by_sha.get(change["commit_sha"])
            if not commit:
                continue
            path = change["path"]
            entry = stats[path]
            entry.commits.add(commit["sha"])
            entry.additions += int(change.get("additions", 0))
            entry.deletions += int(change.get("deletions", 0))
            author = commit.get("author_email") or commit.get("author_name") or "unknown"
            changes = int(change.get("additions", 0)) + int(change.get("deletions", 0))
            entry.authors[author] = entry.authors.get(author, 0.0) + float(changes)
            entry.last_ts = max(entry.last_ts, int(commit["ts"]))
            if int(commit["ts"]) >= recent_start:
                entry.churn_recent += changes
            if int(commit.get("is_bugfix", 0)):
                entry.bugfix_commits.add(commit["sha"])
            age = self.as_of - int(commit["ts"])
            if age <= self.thresholds.fix_pressure_baseline_days * 86400:
                weight = recency_weight(int(commit["ts"]), self.as_of, 60.0)
                entry.fix_weight_total += weight
                if int(commit.get("is_bugfix", 0)):
                    entry.fix_weight_bugfix += weight
                if age <= self.thresholds.fix_pressure_recent_days * 86400:
                    entry.recent_fix_weight_total += weight
                    if int(commit.get("is_bugfix", 0)):
                        entry.recent_fix_weight_bugfix += weight
                else:
                    entry.baseline_fix_weight_total += weight
                    if int(commit.get("is_bugfix", 0)):
                        entry.baseline_fix_weight_bugfix += weight
        self.path_stats = dict(stats)

    def _build_series(self) -> None:
        if not self.commits:
            self.weekly = []
            self.series = {}
            return
        start = week_start(min(int(c["ts"]) for c in self.commits))
        end = week_start(self.as_of)
        buckets = [day.isoformat() for day in weeks_between(start, end)]
        bucket_set = set(buckets)
        weekly_map: dict[str, dict] = {
            bucket: {"bucket": bucket, "commits": 0, "bugfix": 0, "churn": 0, "authors": defaultdict(float), "files": set()}
            for bucket in buckets
        }
        for change in self.commit_files:
            commit = self.commits_by_sha.get(change["commit_sha"])
            if not commit:
                continue
            bucket = week_key(int(commit["ts"]))
            if bucket not in bucket_set:
                continue
            row = weekly_map[bucket]
            row["churn"] += int(change.get("additions", 0)) + int(change.get("deletions", 0))
            author = commit.get("author_email") or commit.get("author_name") or "unknown"
            row["authors"][author] += float(
                int(change.get("additions", 0)) + int(change.get("deletions", 0))
            )
            row["files"].add(change["path"])
        for commit in self.commits:
            bucket = week_key(int(commit["ts"]))
            if bucket in bucket_set:
                weekly_map[bucket]["commits"] += 1
                weekly_map[bucket]["bugfix"] += int(commit.get("is_bugfix", 0))

        churn_values = [float(weekly_map[b]["churn"]) for b in buckets]
        commit_values = [float(weekly_map[b]["commits"]) for b in buckets]
        bugfix_values = [float(weekly_map[b]["bugfix"]) for b in buckets]
        top_share_values: list[float] = []
        volatility_values: list[float] = []

        for index, bucket in enumerate(buckets):
            authors = weekly_map[bucket]["authors"]
            top_share_values.append(safe_div(max(authors.values(), default=0.0), sum(authors.values())))

        window = 8
        for index in range(len(buckets)):
            start_index = max(0, index - window + 1)
            values = churn_values[start_index : index + 1]
            if values and mean(values) > 0:
                avg = mean(values)
                variance = sum((v - avg) ** 2 for v in values) / len(values)
                volatility_values.append(math.sqrt(variance) / avg)
            else:
                volatility_values.append(0.0)

        drift_values: list[float] = [0.0] * len(buckets)
        window_share: list[float] = [0.0] * len(buckets)
        for index in range(len(buckets)):
            start_index = max(0, index - 3)
            authors: dict[str, float] = defaultdict(float)
            for cursor in range(start_index, index + 1):
                for author, value in weekly_map[buckets[cursor]]["authors"].items():
                    authors[author] += value
            share = safe_div(max(authors.values(), default=0.0), sum(authors.values()))
            window_share[index] = share
            if index >= 4:
                drift_values[index] = abs(share - window_share[index - 4])

        self.weekly = []
        for index, bucket in enumerate(buckets):
            row = weekly_map[bucket]
            self.weekly.append(
                {
                    "bucket": bucket,
                    "commits": row["commits"],
                    "bugfix": row["bugfix"],
                    "churn": row["churn"],
                    "authors": len(row["authors"]),
                    "top_share": round(top_share_values[index], 6),
                    "churn_volatility": round(volatility_values[index], 6),
                    "ownership_drift": round(drift_values[index], 6),
                    "ownership_top_share": round(window_share[index], 6),
                }
            )

        def rows(name: str, values: Sequence[float]) -> list[dict]:
            return [
                {"metric": name, "bucket": buckets[i], "value": round(float(values[i]), 6)}
                for i in range(len(buckets))
            ]

        series: dict[str, list[dict]] = {}
        for name, values in (
            ("churn_weekly", churn_values),
            ("commits_weekly", commit_values),
            ("bugfix_weekly", bugfix_values),
            ("churn_volatility", volatility_values),
            ("ownership_drift", drift_values),
            ("ownership_top_share", window_share),
        ):
            series[name] = rows(name, values)
        self.series = series

    # ------------------------------------------------------------ ownership
    def ownership(self, paths: Iterable[str]) -> dict:
        paths_set = set(paths)
        authors: dict[str, float] = defaultdict(float)
        commits: set[str] = set()
        churn = 0
        for path in paths_set:
            stats = self.path_stats.get(path)
            if not stats:
                continue
            for author, value in stats.authors.items():
                authors[author] += value
            commits |= stats.commits
            churn += stats.churn_total
        total = sum(authors.values())
        bf, authors_count = bus_factor_of(dict(authors))
        return {
            "authors": dict(authors),
            "authors_count": authors_count,
            "top_share": safe_div(max(authors.values(), default=0.0), total),
            "entropy": normalized_entropy(authors.values()),
            "bus_factor": bf,
            "commits": len(commits),
            "churn": churn,
        }

    def module_ownership(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for module, paths in self.modules.items():
            result[module] = self.ownership(paths)
        return result

    # --------------------------------------------------------------- basics
    @property
    def project_ownership(self) -> dict:
        product_paths = [path for path in self.files_by_path if not is_support_path(path)]
        return self.ownership(product_paths or self.files_by_path.keys())

    def total_loc(self) -> int:
        return sum(int(f.get("loc", 0)) for f in self.files)

    def file_metric(self, path: str, metric: str, default: float = 0.0) -> float:
        row = self.files_by_path.get(path, {})
        return float(row.get(metric, default) or 0.0)

    def p90_complexity(self) -> float:
        return percentile([self.file_metric(p, "complexity_max") for p in self.files_by_path], 0.90)

    def p75_churn(self) -> float:
        return percentile([self.path_stats.get(p, PathStats()).churn_total for p in self.files_by_path], 0.75)

    def recent_series(self, name: str, count: int) -> list[float]:
        rows = self.series.get(name, [])[-count:]
        return [float(row["value"]) for row in rows]

    def file_url(self, path: str) -> str:
        return path


def build_context(
    repo: dict,
    files: list[dict],
    commits: list[dict],
    commit_files: list[dict],
    entities: list[dict],
    refs: list[dict],
    imports: list[dict],
    file_graph: DependencyGraph,
    entity_graph: DependencyGraph,
    thresholds: Thresholds,
    history_metrics: dict[str, dict] | None = None,
) -> RepoContext:
    as_of = max((int(c["ts"]) for c in commits), default=0)
    return RepoContext(
        repo=repo,
        as_of=as_of,
        files=files,
        commits=commits,
        commit_files=commit_files,
        entities=entities,
        refs=refs,
        imports=imports,
        file_graph=file_graph,
        entity_graph=entity_graph,
        thresholds=thresholds,
        history_metrics=history_metrics or {},
    )


class MetricSet:
    """Удобный доступ к значениям метрик по (scope, target, metric)."""

    def __init__(self, values: Sequence[dict]) -> None:
        self._values: dict[tuple[str, str, str], float] = {}
        self._rows: list[dict] = []
        for row in values:
            key = (row["scope"], row["target"], row["metric"])
            self._values[key] = float(row["value"])
            self._rows.append(row)

    def get(self, metric: str, target: str = "project", scope: str = "project", default: float = 0.0) -> float:
        return self._values.get((scope, target, metric), default)

    def has(self, metric: str, target: str, scope: str) -> bool:
        return (scope, target, metric) in self._values

    def files(self, metric: str) -> list[tuple[str, float]]:
        return [
            (target, value)
            for (scope, target, name), value in self._values.items()
            if scope == "file" and name == metric
        ]

    def modules(self, metric: str) -> list[tuple[str, float]]:
        return [
            (target, value)
            for (scope, target, name), value in self._values.items()
            if scope == "module" and name == metric
        ]

    def rows(self) -> list[dict]:
        return list(self._rows)
