"""Тесты командной строки: add, index, repos, report, compare, research, plugins, bench."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from projectpulse.app import main
from tests.helpers import make_sample_repo


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="pp_cli_")
        cls.root = Path(cls.temp.name)
        cls.home = cls.root / "home"
        cls.repo_path = cls.root / "cli_repo"
        make_sample_repo(cls.repo_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _run(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_01_repos_empty(self) -> None:
        code, out, err = self._run("repos", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), [])

    def test_02_add_and_index_json(self) -> None:
        code, out, err = self._run("add", "--repo", str(self.repo_path), "--name", "CLI Repo")
        self.assertEqual(code, 0, err)
        added = json.loads(out)
        self.assertEqual(added["name"], "CLI Repo")

        code, out, err = self._run(
            "index", "--repo", str(self.repo_path), "--mode", "full", "--json", "--quiet"
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "full")
        self.assertEqual(payload["commits_new"], 4)
        self.assertGreaterEqual(payload["snapshots"], 3)
        self.assertGreaterEqual(payload["health"], 0)

    def test_03_repos_after_index(self) -> None:
        code, out, err = self._run("repos", "--json")
        self.assertEqual(code, 0, err)
        repos = json.loads(out)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["name"], "CLI Repo")
        self.assertEqual(repos[0]["commits_total"], 4)

    def test_04_report_html(self) -> None:
        target = self.root / "cli_report.html"
        code, out, err = self._run(
            "report", "--repo", str(self.repo_path), "--format", "html", "--out", str(target)
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(target.exists())
        self.assertIn("HTML:", out)

    def test_05_compare_and_research(self) -> None:
        code, out, err = self._run(
            "compare", "--a", str(self.repo_path), "--b", str(self.repo_path), "--json"
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(len(payload["indicators"]), 5)

        research_target = self.root / "cli_research"
        code, out, err = self._run(
            "research",
            "--healthy",
            str(self.repo_path),
            "--problematic",
            str(self.repo_path),
            "--no-index",
            "--out",
            str(research_target),
            "--json",
        )
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertIn("hypothesis", result)
        self.assertTrue((research_target / "research_report.md").exists())

    def test_06_plugins_catalog(self) -> None:
        code, out, err = self._run("plugins", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertGreaterEqual(len(payload["metrics"]), 10)
        self.assertGreaterEqual(len(payload["rules"]), 8)

    def test_07_bench(self) -> None:
        code, out, err = self._run("bench", "--repo", str(self.repo_path), "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertIn("full", payload)
        self.assertIn("incremental", payload)
        self.assertIn("incremental_no_changes", payload)
        self.assertGreaterEqual(payload["full"]["duration_ms"], 0)
        self.assertEqual(payload["incremental"]["runs"][0]["commits_new"], 1)

    def test_08_missing_repo_error(self) -> None:
        code, out, err = self._run("index", "--repo", str(self.root / "missing"), "--quiet")
        self.assertEqual(code, 1)
        self.assertIn("Ошибка", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
