"""Тесты конфигурации и реестров плагинов."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projectpulse.analysis.metrics.builtin import default_metrics
from projectpulse.analysis.rules.builtin import default_rules
from projectpulse.core.config import AppConfig, Thresholds, packaged_plugins_dir
from projectpulse.core.plugins import (
    MetricRegistry,
    PluginError,
    PluginManager,
    RuleRegistry,
    ServiceContainer,
)


class ConfigTests(unittest.TestCase):
    def test_thresholds_roundtrip_and_unknown_keys(self) -> None:
        data = Thresholds().to_dict()
        data["unknown"] = 1
        data["churn_spike_z"] = 3.5
        restored = Thresholds.from_dict(data)
        self.assertEqual(restored.churn_spike_z, 3.5)
        self.assertFalse(hasattr(restored, "unknown"))

    def test_app_config_creates_dirs_and_reads_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pp_cfg_") as folder:
            home = Path(folder) / "home"
            config = AppConfig.load(home)
            self.assertTrue(config.paths.db_path.parent.exists())
            self.assertTrue(config.paths.reports_dir.exists())
            (home / "thresholds.json").write_text(json.dumps({"hotspot_min_complexity": 11}), encoding="utf-8")
            loaded = AppConfig.load(home)
            self.assertEqual(loaded.thresholds.hotspot_min_complexity, 11)

    def test_broken_override_falls_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pp_cfg_") as folder:
            home = Path(folder) / "home"
            AppConfig.load(home)
            (home / "thresholds.json").write_text("{broken", encoding="utf-8")
            loaded = AppConfig.load(home)
            self.assertEqual(loaded.thresholds, Thresholds())

    def test_packaged_plugins_dir(self) -> None:
        self.assertIn("plugins", str(packaged_plugins_dir()))


class RegistryTests(unittest.TestCase):
    def test_metric_registry(self) -> None:
        registry = MetricRegistry()
        metric = default_metrics()[0]
        registry.register(metric)
        self.assertEqual(registry.names(), [metric.name])
        self.assertEqual(registry.get(metric.name), metric)
        registry.register(metric, source="test")
        self.assertEqual(registry.sources()[metric.name], "test")
        self.assertEqual(registry.all(), [metric])
        with self.assertRaises(PluginError):
            registry.register(object())

    def test_rule_registry(self) -> None:
        registry = RuleRegistry()
        rule = default_rules()[0]
        registry.register(rule)
        self.assertEqual(registry.names(), [rule.name])
        self.assertEqual(registry.get(rule.name), rule)

    def test_service_container(self) -> None:
        container = ServiceContainer()
        container.register("a", 1)
        self.assertEqual(container.get("a"), 1)
        self.assertEqual(container.get("missing", 7), 7)
        with self.assertRaises(PluginError):
            container.require("missing")
        self.assertEqual(container.names(), ["a"])


class PluginLoadingTests(unittest.TestCase):
    def test_load_plugin_file(self) -> None:
        plugin = '''
from projectpulse.analysis.metrics.base import Metric, MetricValue
from projectpulse.analysis.rules.base import Finding, Rule


class DemoMetric(Metric):
    name = "demo_metric"
    kind = "plugin"

    def compute(self, ctx):
        return [MetricValue("project", "project", "demo_metric", 1.0)]


class DemoRule(Rule):
    name = "demo_rule"

    def evaluate(self, ctx, metrics):
        return [Finding("demo_rule", "info", "project", "demo", "demo", "demo")]


METRICS = [DemoMetric]
RULES = [DemoRule]


def register(container):
    container.register("demo", "ok")
'''
        with tempfile.TemporaryDirectory(prefix="pp_plugin_") as folder:
            path = Path(folder) / "demo_plugin.py"
            path.write_text(plugin, encoding="utf-8")
            metrics = MetricRegistry()
            rules = RuleRegistry()
            container = ServiceContainer()
            manager = PluginManager(metrics, rules, container, [Path(folder)])
            loaded = manager.load_all()
            self.assertEqual(metrics.names(), ["demo_metric"])
            self.assertEqual(rules.names(), ["demo_rule"])
            self.assertEqual(container.get("demo"), "ok")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(len(loaded[0].info), 3)

    def test_broken_plugin_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pp_plugin_") as folder:
            (Path(folder) / "bad.py").write_text("this is not python !!!", encoding="utf-8")
            metrics = MetricRegistry()
            rules = RuleRegistry()
            manager = PluginManager(metrics, rules, ServiceContainer(), [Path(folder)])
            loaded = manager.load_all()
            self.assertEqual(loaded, [])
            self.assertEqual(metrics.names(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
