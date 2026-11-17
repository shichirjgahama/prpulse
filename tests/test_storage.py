"""Тесты слоя хранения SQLite."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projectpulse.storage.db import Database, Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="pp_db_")
        self.database = Database(Path(self.tempdir.name) / "test.db")
        self.store = Store(self.database)
        self.repo = self.store.add_repo("Demo", str(Path(self.tempdir.name) / "demo"))
        self.repo_id = int(self.repo["id"])

    def tearDown(self) -> None:
        self.database.close()
        self.tempdir.cleanup()

    def _seed(self) -> int:
        run_id = self.store.start_run(self.repo_id, "full", "a" * 40)
        commits = [
            {
                "sha": "c1", "author_name": "Alice", "author_email": "a@example.com",
                "ts": 1700000000, "message": "init", "is_bugfix": 0,
                "insertions": 10, "deletions": 0, "files_changed": 1,
            },
            {
                "sha": "c2", "author_name": "Bob", "author_email": "b@example.com",
                "ts": 1700100000, "message": "fix bug", "is_bugfix": 1,
                "insertions": 2, "deletions": 1, "files_changed": 1,
            },
        ]
        changes = [
            {"commit_sha": "c1", "path": "a.py", "additions": 10, "deletions": 0},
            {"commit_sha": "c2", "path": "a.py", "additions": 2, "deletions": 1},
        ]
        self.store.insert_commits(self.repo_id, commits, changes)
        self.store.upsert_files(
            self.repo_id,
            [
                {
                    "path": "a.py", "blob_sha": "b1", "language": "python", "size_bytes": 100,
                    "loc": 10, "sloc": 8, "comments": 1, "blanks": 1,
                    "complexity_total": 3, "complexity_max": 2, "functions": 1,
                    "classes": 0, "todo_count": 0, "parse_error": None,
                }
            ],
        )
        self.store.replace_all_analysis(
            self.repo_id,
            [{"path": "a.py", "blob_sha": "b1", "loc": 10, "sloc": 8, "comments": 1, "blanks": 1, "complexity_total": 3, "complexity_max": 2, "functions": 1, "classes": 0, "todo_count": 0, "size_bytes": 100}],
            [{"entity_id": "function:a.py:f", "kind": "function", "name": "f", "qualname": "f", "path": "a.py", "lineno": 1, "end_lineno": 2, "complexity": 2, "is_public": 1, "parent_id": None}],
            [{"src_id": "function:a.py:f", "kind": "call", "target": "g", "path": "a.py", "lineno": 2}],
            [{"path": "a.py", "module": "os", "level": 0, "names": None, "lineno": 1}],
        )
        self.store.create_snapshot(
            self.repo_id,
            label="HEAD (main)",
            ref="HEAD",
            commit_sha="c2",
            nodes=[{"node_id": "a.py", "kind": "file", "name": "a.py", "path": "a.py", "loc": 10, "complexity": 3}],
            edges=[],
            cycles_count=0,
            loc_total=10,
            metrics={"files": 1},
        )
        self.store.insert_health(run_id, self.repo_id, 72.5, {"label": "ok", "components": {}})
        self.store.insert_findings(
            run_id,
            self.repo_id,
            [{"rule": "demo", "severity": "warning", "target": "a.py", "title": "T", "explanation": "E", "recommendation": "R", "value": {"x": 1}}],
        )
        self.store.replace_metric_values(
            run_id,
            self.repo_id,
            [{"scope": "project", "target": "project", "metric": "loc", "value": 10, "extra": {}}],
        )
        self.store.replace_series(
            self.repo_id,
            [{"metric": "commits_weekly", "bucket": "2024-01-01", "value": 2}],
        )
        self.store.finish_run(run_id, duration_ms=5, head_sha="c2", commits_seen=2, commits_new=2, files_parsed=1)
        return run_id

    def test_repo_and_runs(self) -> None:
        self.assertEqual(self.store.get_repo(self.repo_id)["name"], "Demo")
        self.assertIsNone(self.store.get_repo(path="/missing"))
        self.assertEqual(len(self.store.list_repos()), 1)
        run_id = self._seed()
        self.store.finish_run(run_id, duration_ms=123, head_sha="c2", commits_seen=2, commits_new=2, files_parsed=1)
        run = self.store.latest_run(self.repo_id)
        self.assertEqual(run["status"], "ok")
        self.assertEqual(run["duration_ms"], 123)
        self.assertEqual(len(self.store.list_runs(self.repo_id)), 1)

    def test_commits_files_and_analysis(self) -> None:
        self._seed()
        self.assertEqual(self.store.counts(self.repo_id)["commits"], 2)
        self.assertEqual(self.store.counts(self.repo_id)["authors"], 2)
        self.assertEqual(len(self.store.get_commits(self.repo_id)), 2)
        self.assertEqual(len(self.store.get_commit_files(self.repo_id)), 2)
        self.assertEqual(len(self.store.get_files(self.repo_id)), 1)
        self.assertEqual(len(self.store.get_entities(self.repo_id)), 1)
        self.assertEqual(len(self.store.get_entity_refs(self.repo_id)), 1)
        self.assertEqual(len(self.store.get_file_imports(self.repo_id)), 1)
        stats = self.store.stats(self.repo_id)
        self.assertEqual(stats["loc"], 10)
        self.assertEqual(stats["files"], 1)

    def test_replace_file_and_delete(self) -> None:
        self._seed()
        self.store.replace_file_analysis(
            self.repo_id,
            "b.py",
            {"path": "b.py", "blob_sha": "b2", "loc": 5, "sloc": 4, "comments": 0, "blanks": 1, "complexity_total": 1, "complexity_max": 1, "functions": 0, "classes": 0, "todo_count": 0, "size_bytes": 20},
            [],
            [],
            [],
        )
        self.assertEqual(len(self.store.get_files(self.repo_id)), 2)
        self.store.delete_files(self.repo_id, ["b.py"])
        self.assertEqual(len(self.store.get_files(self.repo_id)), 1)

    def test_metrics_findings_health_series(self) -> None:
        run_id = self._seed()
        self.assertEqual(self.store.project_metric(run_id, "loc"), 10)
        self.assertEqual(self.store.metric_map(run_id)[("project", "project", "loc")], 10)
        health = self.store.get_health(run_id)
        self.assertEqual(health["score"], 72.5)
        self.assertEqual(health["components"]["label"], "ok")
        self.assertEqual(self.store.latest_health(self.repo_id)["score"], 72.5)
        findings = self.store.get_findings(run_id)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "warning")
        self.assertEqual(len(self.store.get_series(self.repo_id)), 1)
        self.assertEqual(len(self.store.series_map(self.repo_id)["commits_weekly"]), 1)
        self.store.save_research("A", "B", "H", {"ok": True})
        self.assertEqual(self.database.scalar("SELECT COUNT(*) FROM research_results"), 1)

    def test_snapshots(self) -> None:
        self._seed()
        snapshots = self.store.list_snapshots(self.repo_id)
        self.assertEqual(len(snapshots), 1)
        snapshot_id = int(snapshots[0]["id"])
        self.assertEqual(len(self.store.get_snapshot_nodes(snapshot_id)), 1)
        self.assertEqual(self.store.latest_snapshot(self.repo_id, ref="HEAD")["id"], snapshot_id)
        self.assertIsNotNone(self.store.get_snapshot(snapshot_id))

    def test_clear_repo_data_cascades(self) -> None:
        self._seed()
        self.store.clear_repo_data(self.repo_id)
        self.assertEqual(self.store.counts(self.repo_id)["commits"], 0)
        self.assertEqual(self.store.get_files(self.repo_id), [])
        self.assertEqual(self.store.list_snapshots(self.repo_id), [])
        self.assertEqual(self.database.scalar("SELECT COUNT(*) FROM snapshot_nodes"), 0)
        self.assertEqual(self.store.list_runs(self.repo_id), [])
        repo = self.store.get_repo(self.repo_id)
        self.assertIsNone(repo["head_sha"])
        self.assertEqual(repo["commits_total"], 0)

    def test_delete_repo_cascades(self) -> None:
        self._seed()
        self.store.delete_repo(self.repo_id)
        self.assertEqual(self.store.list_repos(), [])
        self.assertEqual(self.store.get_commits(self.repo_id), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
