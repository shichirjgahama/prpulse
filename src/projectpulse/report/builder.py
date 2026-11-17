"""Сбор данных для HTML/PDF отчёта."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from projectpulse import __version__
from projectpulse.core.config import AppConfig
from projectpulse.core.utils import iso, safe_div, week_key
from projectpulse.storage.db import Store


@dataclass
class ReportData:
    repo: dict
    run: dict
    health: dict
    stats: dict
    metrics: dict[tuple[str, str, str], float]
    metric_rows: list[dict]
    findings: list[dict]
    series: dict[str, list[dict]]
    snapshots: list[dict]
    runs: list[dict]
    top_hotspots: list[dict]
    top_churn: list[dict]
    top_complexity: list[dict]
    top_fix_pressure: list[dict]
    modules: list[dict]
    cycles: list[list[str]]
    generated_at: str
    tool_version: str = __version__
    thresholds: dict = field(default_factory=dict)

    def metric(self, name: str, scope: str = "project", target: str = "project", default: float = 0.0) -> float:
        return float(self.metrics.get((scope, target, name), default))


def _snapshot_metrics(row: dict) -> dict:
    try:
        return json.loads(row.get("metrics_json") or "{}")
    except ValueError:
        return {}


def _snapshot_diff(store: Store, previous: dict, current: dict) -> dict:
    old_nodes = {row["node_id"]: row for row in store.get_snapshot_nodes(int(previous["id"]))}
    new_nodes = {row["node_id"]: row for row in store.get_snapshot_nodes(int(current["id"]))}
    old_edges = {(row["src"], row["dst"], row["kind"]) for row in store.get_snapshot_edges(int(previous["id"]))}
    new_edges = {(row["src"], row["dst"], row["kind"]) for row in store.get_snapshot_edges(int(current["id"]))}
    changed_nodes = 0
    for node_id in set(old_nodes) & set(new_nodes):
        if (
            old_nodes[node_id].get("complexity", 0),
            old_nodes[node_id].get("loc", 0),
        ) != (
            new_nodes[node_id].get("complexity", 0),
            new_nodes[node_id].get("loc", 0),
        ):
            changed_nodes += 1
    return {
        "added_nodes": len(set(new_nodes) - set(old_nodes)),
        "removed_nodes": len(set(old_nodes) - set(new_nodes)),
        "changed_nodes": changed_nodes,
        "added_edges": len(new_edges - old_edges),
        "removed_edges": len(old_edges - new_edges),
    }


def _top_files(files: Sequence[dict], metrics: dict, metric: str, limit: int = 10, key: str | None = None) -> list[dict]:
    rows = []
    for file in files:
        path = file["path"]
        value = metrics.get(("file", path, metric), 0.0)
        rows.append(
            {
                "path": path,
                "value": float(value),
                "loc": int(file.get("loc", 0)),
                "complexity_max": int(file.get("complexity_max", 0)),
                "churn_90d": metrics.get(("file", path, "churn_90d"), 0.0),
                "top_share": metrics.get(("file", path, "ownership_top_share"), 0.0),
                "fix_pressure": metrics.get(("file", path, "fix_pressure_recent"), 0.0),
                "interface_volatility": metrics.get(("file", path, "interface_volatility"), 0.0),
            }
        )
    rows.sort(key=lambda row: (row[key] if key else row["value"], row["path"]), reverse=True)
    return rows[:limit]


def build_report_data(store: Store, repo_id: int, config: AppConfig) -> ReportData:
    repo = store.get_repo(repo_id)
    if not repo:
        raise ValueError("Репозиторий не найден")
    run = store.latest_run(repo_id)
    if not run:
        raise ValueError("Нет успешной индексации: сформируйте отчёт после импорта")
    run_id = int(run["id"])
    health = store.get_health(run_id) or {"score": 0.0, "components": {}}
    metric_rows = store.get_metric_values(run_id)
    metrics = {(row["scope"], row["target"], row["metric"]): float(row["value"]) for row in metric_rows}
    findings = store.get_findings(run_id)
    series_rows = store.get_series(repo_id)
    series: dict[str, list[dict]] = {}
    for row in series_rows:
        series.setdefault(row["metric"], []).append(row)
    for rows in series.values():
        rows.sort(key=lambda row: row["bucket"])

    files = store.get_files(repo_id)
    commit_week = {row["sha"]: week_key(int(row["ts"])) for row in store.get_commits(repo_id)}
    snapshots_raw = store.list_snapshots(repo_id)
    snapshots: list[dict] = []
    previous = None
    for row in snapshots_raw:
        item = {
            "id": row["id"],
            "label": row["label"],
            "ref": row.get("ref"),
            "commit_sha": row.get("commit_sha"),
            "created_at": row.get("created_at"),
            "nodes": row.get("nodes_count", 0),
            "edges": row.get("edges_count", 0),
            "cycles": row.get("cycles_count", 0),
            "loc": row.get("loc_total", 0),
            "metrics": _snapshot_metrics(row),
            "week": commit_week.get(row.get("commit_sha")),
            "diff": _snapshot_diff(store, previous, row) if previous else None,
        }
        snapshots.append(item)
        previous = row

    cycles: list[list[str]] = []
    for finding in findings:
        if finding["rule"] == "dependency_cycle":
            try:
                names = json.loads(finding.get("value_json") or "{}").get("cycle_nodes", [])
            except ValueError:
                names = []
            if names:
                cycles.append(names)

    modules: list[dict] = []
    for (scope, target, metric), value in metrics.items():
        if scope == "module" and metric == "bus_factor":
            modules.append(
                {
                    "name": target,
                    "bus_factor": value,
                    "commits": metrics.get(("module", target, "module_commits"), 0.0),
                    "authors": metrics.get(("module", target, "bus_factor_authors"), 0.0),
                    "top_share": metrics.get(("module", target, "ownership_top_share"), 0.0),
                    "coupling": metrics.get(("module", target, "coupling_pressure"), 0.0),
                }
            )
    modules.sort(key=lambda row: (row["bus_factor"], -row["commits"], row["name"]))

    data = ReportData(
        repo=repo,
        run=run,
        health=health,
        stats=store.stats(repo_id),
        metrics=metrics,
        metric_rows=metric_rows,
        findings=findings,
        series=series,
        snapshots=snapshots,
        runs=store.list_runs(repo_id, limit=10),
        top_hotspots=_top_files(files, metrics, "churn_90d", limit=10, key="churn_90d"),
        top_churn=_top_files(files, metrics, "churn_90d", limit=10, key="churn_90d"),
        top_complexity=_top_files(files, metrics, "complexity_max", limit=10, key="complexity_max"),
        top_fix_pressure=_top_files(files, metrics, "fix_pressure_recent", limit=10, key="fix_pressure"),
        modules=modules,
        cycles=cycles,
        generated_at=iso(),
        thresholds=config.thresholds.to_dict(),
    )
    # Горячие точки: произведение сложности и churn.
    for row in data.top_hotspots:
        row["hotspot_score"] = safe_div(row["complexity_max"] * row["churn_90d"], 100.0)
    data.top_hotspots.sort(key=lambda row: (row["hotspot_score"], row["path"]), reverse=True)
    return data
