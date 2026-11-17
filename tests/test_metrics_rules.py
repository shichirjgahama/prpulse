"""Тесты метрик, правил и индекса здоровья."""

from __future__ import annotations

import unittest

from projectpulse.analysis.context import MetricSet
from projectpulse.analysis.health import compute_health
from projectpulse.analysis.metrics.base import MetricValue
from projectpulse.analysis.metrics.builtin import compute_metrics, default_metrics
from projectpulse.analysis.rules.builtin import (
    ApiVolatilityRule,
    BusFactorRule,
    ChurnSpikeRule,
    ChurnVolatilityRiseRule,
    CycleRule,
    FixPressureTrendRule,
    GodModuleRule,
    HotspotRule,
    OwnershipConcentrationRule,
    OwnershipDriftRule,
    default_rules,
)
from projectpulse.analysis.rules.engine import evaluate_rules, severity_counts
from projectpulse.core.config import Thresholds
from tests.helpers import make_context


SOURCES = {
    "pkg/__init__.py": '"""Init."""\n\nfrom .a import alpha\n',
    "pkg/a.py": '"""A."""\n\nfrom .b import beta\n\n\ndef alpha(value):\n    if value > 0 and value < 10:\n        return beta(value)\n    return 0\n',
    "pkg/b.py": '"""B."""\n\nfrom .a import alpha\n\n\ndef beta(value):\n    for index in range(3):\n        value += index\n    return alpha(value) if value > 100 else value\n',
    "pkg/core.py": '"""Core."""\n\n\ndef core(value):\n    try:\n        return 100 // value\n    except ZeroDivisionError:\n        return 0\n',
}


def metric_rows(**project: float) -> list[dict]:
    rows = []
    for name, value in project.items():
        rows.append(
            MetricValue("project", "project", name, float(value)).as_dict()
        )
    return rows


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        commits = [
            {"sha": "c1", "ts": 1704099600, "author_email": "alice@example.com", "is_bugfix": 0},
            {"sha": "c2", "ts": 1705309200, "author_email": "bob@example.com", "is_bugfix": 1},
            {"sha": "c3", "ts": 1709632800, "author_email": "carol@example.com", "is_bugfix": 0},
        ]
        changes = [
            {"commit_sha": "c1", "path": "pkg/a.py", "additions": 10, "deletions": 0},
            {"commit_sha": "c1", "path": "pkg/b.py", "additions": 5, "deletions": 0},
            {"commit_sha": "c2", "path": "pkg/a.py", "additions": 10, "deletions": 0},
            {"commit_sha": "c3", "path": "pkg/core.py", "additions": 100, "deletions": 10},
        ]
        self.context = make_context(SOURCES, commits, changes)
        self.rows = compute_metrics(default_metrics(), self.context)
        self.metrics = MetricSet(self.rows)

    def test_default_metric_catalog(self) -> None:
        metrics = default_metrics()
        self.assertEqual(len(metrics), 10)
        kinds = {}
        for metric in metrics:
            kinds[metric.kind] = kinds.get(metric.kind, 0) + 1
        self.assertEqual(kinds.get("classic"), 5)
        self.assertEqual(kinds.get("custom"), 3)
        self.assertEqual(kinds.get("series"), 2)

    def test_project_metrics_present(self) -> None:
        names = {row["metric"] for row in self.rows if row["scope"] == "project"}
        expected = {
            "loc", "sloc", "churn_total", "churn_90d", "churn_density_90d",
            "complexity_total", "complexity_max", "avg_function_complexity",
            "ownership_top_share", "bus_factor", "bus_factor_authors",
            "fix_pressure_recent", "coupling_pressure_avg", "cycle_count",
            "interface_volatility", "churn_volatility", "ownership_drift",
        }
        self.assertTrue(expected.issubset(names), expected - names)

    def test_churn_and_ownership_formulas(self) -> None:
        self.assertEqual(self.metrics.get("churn_total"), 135)
        self.assertEqual(self.metrics.get("churn_90d"), 135)
        self.assertAlmostEqual(self.metrics.get("churn_density_90d"), 135 / self.context.total_loc() * 100)
        self.assertGreater(self.metrics.get("ownership_top_share"), 0.5)
        self.assertEqual(self.metrics.get("bus_factor"), 1)
        self.assertEqual(self.metrics.get("bus_factor_authors"), 3)

    def test_fix_pressure_and_interface(self) -> None:
        self.assertGreaterEqual(self.metrics.get("fix_pressure_recent"), 0.0)
        self.assertLessEqual(self.metrics.get("fix_pressure_recent"), 1.0)
        self.assertEqual(self.metrics.get("interface_volatility"), 0.0)
        self.assertEqual(self.metrics.get("api_volatile_files"), 0)

    def test_cycles_and_coupling(self) -> None:
        self.assertEqual(self.metrics.get("cycle_count"), 1)
        file_cycles = dict(self.metrics.files("in_cycle"))
        self.assertEqual(file_cycles.get("pkg/a.py"), 1.0)
        self.assertEqual(file_cycles.get("pkg/b.py"), 1.0)
        self.assertGreater(self.metrics.get("coupling_pressure_max"), 0.0)

    def test_history_metrics_are_used(self) -> None:
        context = make_context(
            SOURCES,
            history_metrics={
                "pkg/a.py": {
                    "value": 0.75,
                    "public_change_commits": 4,
                    "commits_considered": 8,
                }
            },
        )
        rows = compute_metrics(default_metrics(), context)
        metrics = MetricSet(rows)
        self.assertAlmostEqual(metrics.get("interface_volatility"), 0.75)
        self.assertEqual(metrics.get("api_volatile_files"), 1)


class RuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = make_context(SOURCES)
        self.thresholds = Thresholds()

    def test_default_rule_catalog(self) -> None:
        rules = default_rules()
        self.assertEqual(len(rules), 10)
        self.assertGreaterEqual(sum(1 for rule in rules if rule.trend), 3)

    def test_hotspot_rule(self) -> None:
        context = make_context({f"pkg/m{i}.py": "def f():\n    return 1\n" for i in range(5)})
        rows = []
        for index in range(5):
            path = f"pkg/m{index}.py"
            rows.append(MetricValue("file", path, "complexity_max", [2, 3, 4, 5, 20][index]).as_dict())
            rows.append(MetricValue("file", path, "churn_90d", [1, 2, 3, 4, 200][index]).as_dict())
        findings = HotspotRule().evaluate(context, MetricSet(rows))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].target, "pkg/m4.py")
        self.assertEqual(findings[0].severity, "critical")

    def test_bus_factor_and_ownership_rules(self) -> None:
        rows = [
            MetricValue("module", "pkg", "bus_factor", 1).as_dict(),
            MetricValue("module", "pkg", "module_commits", 15).as_dict(),
            MetricValue("module", "pkg", "bus_factor_authors", 1).as_dict(),
            MetricValue("file", "pkg/a.py", "ownership_top_share", 0.95).as_dict(),
            MetricValue("file", "pkg/a.py", "commit_count", 12).as_dict(),
        ]
        metrics = MetricSet(rows)
        bus = BusFactorRule().evaluate(self.context, metrics)
        self.assertEqual(len(bus), 1)
        self.assertEqual(bus[0].severity, "warning")
        owners = OwnershipConcentrationRule().evaluate(self.context, metrics)
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].target, "pkg/a.py")

    def test_cycle_and_god_module_rules(self) -> None:
        cycles = CycleRule().evaluate(self.context, MetricSet([]))
        self.assertEqual(len(cycles), 1)
        self.assertIn("pkg/a.py", cycles[0].value["cycle_nodes"])
        context = make_context({"pkg/big.py": "def f():\n    return 1\n" * 20})
        context.files_by_path["pkg/big.py"]["loc"] = 400
        rows = [
            MetricValue("file", "pkg/big.py", "fan_in", 6).as_dict(),
            MetricValue("file", "pkg/big.py", "fan_out", 7).as_dict(),
        ]
        findings = GodModuleRule().evaluate(context, MetricSet(rows))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")

    def test_trend_rules(self) -> None:
        context = make_context(SOURCES)
        context.series = {
            "churn_weekly": [
                {"bucket": f"2024-01-{index:02d}", "value": value}
                for index, value in enumerate([10, 12, 9, 11, 10, 12, 9, 11, 10, 12, 9, 11, 500], start=1)
            ]
        }
        spike = ChurnSpikeRule().evaluate(context, MetricSet([]))
        self.assertGreaterEqual(len(spike), 1)
        self.assertEqual(spike[-1].rule, "churn_spike")
        volatility = ChurnVolatilityRiseRule().evaluate(
            context, MetricSet(metric_rows(churn_volatility_recent=0.9, churn_volatility_previous=0.2))
        )
        self.assertEqual(len(volatility), 1)
        pressure = FixPressureTrendRule().evaluate(
            context,
            MetricSet(
                metric_rows(fix_pressure_recent=0.8, fix_pressure_previous=0.2)
                + [MetricValue("file", "pkg/a.py", "fix_pressure_growth", 0.6).as_dict(),
                   MetricValue("file", "pkg/a.py", "fix_pressure_recent", 0.8).as_dict()]
            ),
        )
        self.assertEqual(len(pressure), 1)
        drift = OwnershipDriftRule().evaluate(
            context, MetricSet(metric_rows(ownership_drift=0.5, bus_factor_authors=4))
        )
        self.assertEqual(len(drift), 1)

    def test_api_volatility_rule(self) -> None:
        rows = [
            MetricValue("file", "pkg/a.py", "interface_volatility", 0.8).as_dict(),
            MetricValue("file", "pkg/a.py", "api_change_commits", 4).as_dict(),
        ]
        findings = ApiVolatilityRule().evaluate(self.context, MetricSet(rows))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].target, "pkg/a.py")

    def test_support_paths_are_ignored_by_rules(self) -> None:
        context = make_context(
            {
                "pkg/core.py": "def core():\n    return 1\n",
                "tests/test_core.py": "def test_core():\n    return 1\n" * 20,
                "docs/example.py": "def example():\n    return 1\n" * 20,
            }
        )
        rows = [
            MetricValue("file", "tests/test_core.py", "complexity_max", 50).as_dict(),
            MetricValue("file", "tests/test_core.py", "churn_90d", 500).as_dict(),
            MetricValue("file", "docs/example.py", "ownership_top_share", 1.0).as_dict(),
            MetricValue("file", "docs/example.py", "commit_count", 40).as_dict(),
            MetricValue("module", "tests", "bus_factor", 1).as_dict(),
            MetricValue("module", "tests", "module_commits", 100).as_dict(),
            MetricValue("module", "tests", "bus_factor_authors", 1).as_dict(),
        ]
        metrics = MetricSet(rows)
        self.assertEqual(HotspotRule().evaluate(context, metrics), [])
        self.assertEqual(OwnershipConcentrationRule().evaluate(context, metrics), [])
        self.assertEqual(BusFactorRule().evaluate(context, metrics), [])

    def test_cycle_severity_for_package_reexport(self) -> None:
        context = make_context(
            {
                "pkg/__init__.py": "from .core import core\n",
                "pkg/core.py": "from . import core as itself\n\ndef core():\n    return 1\n",
            }
        )
        findings = CycleRule().evaluate(context, MetricSet([]))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")
        self.assertTrue(findings[0].value["package_reexport"])

    def test_engine_sorts_and_normalizes(self) -> None:
        rows = metric_rows(ownership_drift=0.9, bus_factor_authors=5)
        findings = evaluate_rules(default_rules(), self.context, MetricSet(rows))
        self.assertTrue(findings)
        severities = [finding["severity"] for finding in findings]
        order = {"critical": 0, "warning": 1, "info": 2}
        self.assertEqual(severities, sorted(severities, key=order.get))
        counts = severity_counts(findings)
        self.assertEqual(sum(counts.values()), len(findings))


class HealthTests(unittest.TestCase):
    class FakeMetrics:
        def __init__(self, values: dict | None = None, files: dict | None = None) -> None:
            self.values = values or {}
            self.file_values = files or {}

        def get(self, name: str, target: str = "project", scope: str = "project", default: float = 0.0):
            return self.values.get(name, default)

        def files(self, name: str):
            return list(self.file_values.get(name, {}).items())

    def test_perfect_health(self) -> None:
        context = make_context(SOURCES)
        health = compute_health([], self.FakeMetrics(), context)
        self.assertEqual(health["score"], 100.0)
        self.assertEqual(health["counts"]["critical"], 0)
        self.assertEqual(set(health["components"]), {"risks", "hotspots", "knowledge", "structure"})

    def test_health_is_bounded_and_explained(self) -> None:
        context = make_context(SOURCES)
        findings = [
            {"rule": "x", "severity": "critical", "target": "a", "title": "t"},
        ] * 20
        metrics = self.FakeMetrics(
            {"avg_file_top_share": 0.9, "bus_factor": 1, "bus_factor_authors": 4, "cycle_count": 3, "api_volatile_files": 4},
            {"complexity_max": {"a": 40, "b": 30}, "churn_90d": {"a": 500, "b": 300}},
        )
        health = compute_health(findings, metrics, context)
        self.assertGreaterEqual(health["score"], 0.0)
        self.assertLessEqual(health["score"], 100.0)
        self.assertLess(health["score"], 40)
        self.assertIn("summary", health)
        self.assertEqual(health["counts"]["critical"], 20)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
