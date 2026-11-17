"""Тесты сравнения репозиториев и мини-исследования."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projectpulse.analysis.compare import compare_repos, indicator_delta, relative_gap
from projectpulse.analysis.research import HYPOTHESIS, analyze_repo, research_markdown, run_research
from projectpulse.report.service import write_research
from tests.helpers import append_commit, make_runtime, make_sample_repo, write


class CompareResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="pp_research_")
        cls.root = Path(cls.temp.name)
        cls.runtime = make_runtime(cls.root / "home")
        cls.healthy_path = cls.root / "healthy"
        make_sample_repo(cls.healthy_path)
        cls.healthy = cls.runtime.indexer.add_repository(cls.healthy_path, name="Healthy")
        cls.runtime.indexer.index(int(cls.healthy["id"]), mode="full")

        cls.problem_path = cls.root / "problem"
        make_sample_repo(cls.problem_path)
        append_commit(cls.problem_path)
        write(
            cls.problem_path,
            "pkg/problem.py",
            '"""Проблемный модуль."""\n\n\n'
            + "\n".join(
                f"def branch_{i}(value):\n"
                f"    if value > {i} and value < {i + 100}:\n"
                f"        return value * {i + 1}\n"
                f"    return 0\n"
                for i in range(6)
            ),
        )
        from tests.helpers import commit

        commit(cls.problem_path, "fix crash in problem module", 1717000000, ("Bob", "bob@example.com"))
        cls.problem = cls.runtime.indexer.add_repository(cls.problem_path, name="Problem")
        cls.runtime.indexer.index(int(cls.problem["id"]), mode="full")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runtime.close()
        cls.temp.cleanup()

    def test_compare_structure_and_wins(self) -> None:
        result = compare_repos(self.runtime.store, self.healthy, self.problem)
        self.assertEqual(len(result["indicators"]), 5)
        self.assertEqual(result["wins_a"] + result["wins_b"], sum(1 for row in result["indicators"] if row["better"] != "tie"))
        self.assertIn("Лучше выглядит", result["verdict"])
        self.assertTrue(any(row["key"] == "health" for row in result["indicators"]))
        health_row = next(row for row in result["indicators"] if row["key"] == "health")
        latest_health = self.runtime.store.latest_health(int(self.healthy["id"]))
        self.assertAlmostEqual(health_row["a"], float(latest_health["score"]), places=4)
        self.assertGreater(health_row["a"] + health_row["b"], 0.0)
        for row in result["indicators"]:
            self.assertIn(row["better"], {"a", "b", "tie"})
            self.assertIsInstance(indicator_delta(row), str)
            self.assertGreaterEqual(relative_gap(row), 0.0)

    def test_compare_requires_indexed_repos(self) -> None:
        unindexed_path = self.root / "unindexed"
        make_sample_repo(unindexed_path)
        unindexed = self.runtime.indexer.add_repository(unindexed_path, name="Unindexed")
        with self.assertRaises(ValueError):
            compare_repos(self.runtime.store, self.healthy, unindexed)

    def test_analyze_repo_and_series(self) -> None:
        research = analyze_repo(self.runtime.store, self.healthy)
        self.assertGreater(research.commits, 0)
        self.assertGreater(research.weeks, 0)
        self.assertGreaterEqual(len(research.correlations), 3)
        self.assertTrue(research.sample)
        for item in research.correlations:
            self.assertGreaterEqual(item.n, 3)
            self.assertGreaterEqual(item.pearson, -1.0)
            self.assertLessEqual(item.pearson, 1.0)

    def test_research_markdown_and_files(self) -> None:
        result = run_research(self.runtime.store, self.healthy, self.problem)
        self.assertEqual(result["hypothesis"], HYPOTHESIS)
        self.assertIn("healthy", result)
        self.assertIn("problematic", result)
        text = research_markdown(result)
        for heading in ("Мини-исследование", "Гипотеза", "Методика", "Корреляции", "Выводы", "Ограничения"):
            self.assertIn(heading, text)
        self.assertIn("Пирсон", text)
        md_path, json_path = write_research(result, self.runtime.config, self.root / "research")
        self.assertTrue(md_path.exists())
        self.assertTrue(json_path.exists())
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["hypothesis"], HYPOTHESIS)
        self.assertEqual(
            int(self.runtime.database.scalar("SELECT COUNT(*) FROM research_results")), 1
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
