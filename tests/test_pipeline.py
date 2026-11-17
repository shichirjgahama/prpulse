"""Интеграционные тесты полной, инкрементальной и пересобранной индексации."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import TempDirMixin, append_commit, make_runtime, make_sample_repo, run_git


class PipelineTests(TempDirMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pp_pipe_")
        self.root = Path(self.temp.name)
        self.runtime = make_runtime(self.root / "home")
        self.repo_path = self.root / "sample"
        self.shas = make_sample_repo(self.repo_path)
        self.repo = self.runtime.indexer.add_repository(self.repo_path, name="Sample")
        self.repo_id = int(self.repo["id"])

    def tearDown(self) -> None:
        self.runtime.close()
        self.temp.cleanup()

    def test_full_index_builds_complete_twin(self) -> None:
        result = self.runtime.indexer.index(self.repo_id, mode="full")
        self.assertEqual(result.kind, "full")
        self.assertEqual(result.commits_new, 4)
        self.assertEqual(result.commits_seen, 4)
        self.assertGreaterEqual(result.files_parsed, 5)
        self.assertGreaterEqual(result.snapshots, 3)
        self.assertGreaterEqual(result.health_score, 0)
        self.assertLessEqual(result.health_score, 100)
        self.assertIn("здоровье", result.summary())

        run = self.runtime.store.latest_run(self.repo_id)
        self.assertEqual(run["status"], "ok")
        self.assertEqual(run["kind"], "full")
        counts = self.runtime.store.counts(self.repo_id)
        self.assertEqual(counts["commits"], 4)
        self.assertEqual(counts["authors"], 3)
        self.assertEqual(counts["files"], 7)

        metrics = self.runtime.store.metric_map(int(run["id"]))
        self.assertGreater(metrics[("project", "project", "loc")], 0)
        self.assertGreater(metrics[("project", "project", "complexity_total")], 0)
        self.assertGreaterEqual(metrics[("project", "project", "bus_factor")], 1)
        self.assertIn(("project", "project", "ownership_top_share"), metrics)

        series = self.runtime.store.series_map(self.repo_id)
        for name in ("commits_weekly", "churn_weekly", "bugfix_weekly", "ownership_top_share"):
            self.assertIn(name, series)
            self.assertTrue(series[name])
        snapshots = self.runtime.store.list_snapshots(self.repo_id)
        labels = {item["label"] for item in snapshots}
        refs = {item["ref"] for item in snapshots}
        self.assertTrue(any(label.startswith("HEAD") for label in labels))
        self.assertIn("tag:v1.0", refs)
        self.assertIn("branch:legacy", refs)
        head_snapshot = next(item for item in snapshots if item["label"].startswith("HEAD"))
        self.assertGreater(head_snapshot["nodes_count"], 0)
        nodes = self.runtime.store.get_snapshot_nodes(int(head_snapshot["id"]))
        self.assertTrue(any(node["path"].endswith("core.py") for node in nodes if node.get("path")))
        self.assertIsNotNone(self.runtime.store.get_health(int(run["id"])))

    def test_incremental_after_new_commits(self) -> None:
        self.runtime.indexer.index(self.repo_id, mode="full")
        before = self.runtime.store.counts(self.repo_id)
        append_commit(self.repo_path)
        result = self.runtime.indexer.index(self.repo_id, mode="incremental")
        self.assertEqual(result.kind, "incremental")
        self.assertEqual(result.commits_new, 1)
        self.assertEqual(result.commits_seen, 1)
        self.assertEqual(result.files_parsed, 2)
        after = self.runtime.store.counts(self.repo_id)
        self.assertEqual(after["commits"], before["commits"] + 1)
        self.assertEqual(after["files"], before["files"] + 1)
        paths = {row["path"] for row in self.runtime.store.get_files(self.repo_id)}
        self.assertIn("pkg/newmod.py", paths)
        self.assertEqual(self.runtime.store.latest_run(self.repo_id)["status"], "ok")

    def test_incremental_without_changes_is_reuse(self) -> None:
        self.runtime.indexer.index(self.repo_id, mode="full")
        snapshots_before = len(self.runtime.store.list_snapshots(self.repo_id))
        result = self.runtime.indexer.index(self.repo_id, mode="incremental")
        self.assertEqual(result.kind, "incremental")
        self.assertEqual(result.commits_new, 0)
        self.assertEqual(result.files_parsed, 0)
        self.assertEqual(len(self.runtime.store.list_snapshots(self.repo_id)), snapshots_before)

    def test_rebuild_recreates_state(self) -> None:
        self.runtime.indexer.index(self.repo_id, mode="full")
        append_commit(self.repo_path)
        result = self.runtime.indexer.index(self.repo_id, mode="rebuild")
        self.assertEqual(result.kind, "rebuild")
        self.assertEqual(result.commits_new, 5)
        self.assertEqual(self.runtime.store.counts(self.repo_id)["commits"], 5)
        # Пересборка очищает прежние прогоны и оставляет только текущий.
        runs = self.runtime.store.list_runs(self.repo_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["kind"], "rebuild")
        self.assertEqual(self.runtime.store.get_repo(self.repo_id)["commits_total"], 5)

    def test_diverged_history_falls_back_to_full(self) -> None:
        self.runtime.indexer.index(self.repo_id, mode="full")
        run_git(self.repo_path, "reset", "--hard", self.shas["first"])
        append_commit(self.repo_path, ts=1715000000)
        result = self.runtime.indexer.index(self.repo_id, mode="incremental")
        self.assertEqual(result.kind, "full")
        self.assertTrue(any("предком" in warning for warning in result.warnings))
        self.assertEqual(self.runtime.store.counts(self.repo_id)["commits"], 2)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.runtime.indexer.index(self.repo_id, mode="weird")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
