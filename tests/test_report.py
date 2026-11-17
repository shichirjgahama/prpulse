"""Тесты сборки данных и генерации HTML/PDF отчёта."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projectpulse.core.events import ReportError
from projectpulse.report.builder import build_report_data
from projectpulse.report.service import generate_report, report_basename, safe_name
from tests.helpers import append_commit, make_runtime, make_sample_repo


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="pp_report_")
        cls.root = Path(cls.temp.name)
        cls.runtime = make_runtime(cls.root / "home")
        cls.repo_path = cls.root / "sample"
        make_sample_repo(cls.repo_path)
        append_commit(cls.repo_path)
        cls.repo = cls.runtime.indexer.add_repository(cls.repo_path, name="Отчётный проект")
        cls.repo_id = int(cls.repo["id"])
        cls.runtime.indexer.index(cls.repo_id, mode="full")
        cls.out = cls.root / "reports"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runtime.close()
        cls.temp.cleanup()

    def test_report_data_contains_all_blocks(self) -> None:
        data = build_report_data(self.runtime.store, self.repo_id, self.runtime.config)
        self.assertEqual(data.repo["name"], "Отчётный проект")
        self.assertTrue(data.run)
        self.assertIn("score", data.health)
        self.assertEqual(
            set(data.health["components"]["components"]), {"risks", "hotspots", "knowledge", "structure"}
        )
        self.assertTrue(data.metric_rows)
        self.assertGreater(data.metric("loc"), 0)
        self.assertTrue(data.series)
        self.assertTrue(data.snapshots)
        self.assertTrue(data.top_hotspots or data.top_churn or data.top_complexity)
        self.assertTrue(data.generated_at)

    def test_html_report_has_required_sections(self) -> None:
        written = generate_report(
            self.runtime.store, self.runtime.config, self.repo_id, formats=["html"], out=self.out
        )
        path = Path(written["html"])
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        for heading in ("Сводка", "Риски", "Динамика", "Граф", "Рекомендации"):
            self.assertIn(heading, text)
        self.assertIn("Отчётный проект", text)
        self.assertIn("ProjectPulse", text)
        self.assertGreater(len(text), 5000)
        self.assertNotIn("<script", text.lower())

    def test_pdf_report_is_written(self) -> None:
        written = generate_report(
            self.runtime.store, self.runtime.config, self.repo_id, formats=["pdf"], out=self.out
        )
        path = Path(written["pdf"])
        self.assertTrue(path.exists())
        payload = path.read_bytes()
        self.assertTrue(payload.startswith(b"%PDF"))
        self.assertGreater(len(payload), 5000)

    def test_explicit_file_target_and_name(self) -> None:
        data = build_report_data(self.runtime.store, self.repo_id, self.runtime.config)
        self.assertTrue(report_basename(data).startswith("projectpulse_"))
        self.assertEqual(safe_name("a b/c"), "a_b_c")
        self.assertEqual(safe_name("///"), "repo")
        target = self.root / "single.html"
        written = generate_report(
            self.runtime.store, self.runtime.config, self.repo_id, formats=["html"], out=target
        )
        self.assertEqual(Path(written["html"]), target)
        self.assertTrue(target.exists())

    def test_unknown_format_is_rejected(self) -> None:
        with self.assertRaises(ReportError):
            generate_report(
                self.runtime.store, self.runtime.config, self.repo_id, formats=["docx"], out=self.out
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
