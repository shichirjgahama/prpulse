"""Интеграционные тесты обёртки над git CLI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projectpulse.core.events import GitError
from projectpulse.gitio.runner import GitRunner, is_python_path, mark_bugfix
from tests.helpers import make_sample_repo


class GitRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory(prefix="pp_git_")
        cls.root = Path(cls.tempdir.name)
        cls.repo = cls.root / "repo"
        cls.shas = make_sample_repo(cls.repo)
        cls.runner = GitRunner(timeout=60)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_repository_metadata(self) -> None:
        self.assertEqual(self.runner.ensure_repository(self.repo), self.repo.resolve())
        self.assertEqual(self.runner.head_sha(self.repo), self.shas["fourth"])
        self.assertEqual(self.runner.current_branch(self.repo), "master")
        self.assertEqual(self.runner.commit_count(self.repo), 4)
        self.assertIsNone(self.runner.remote_url(self.repo))
        self.assertTrue(self.runner.version().lower().startswith("git version"))

    def test_ensure_repository_rejects_plain_directory(self) -> None:
        plain = self.root / "plain"
        plain.mkdir(exist_ok=True)
        with self.assertRaises(GitError):
            self.runner.ensure_repository(plain)
        with self.assertRaises(GitError):
            self.runner.ensure_repository(self.root / "missing")

    def test_history(self) -> None:
        records = self.runner.history(self.repo)
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0].sha, self.shas["first"])
        self.assertEqual(records[-1].sha, self.shas["fourth"])
        self.assertEqual([record.message for record in records][1], "fix crash in core and add complex module")
        self.assertTrue(records[1].is_bugfix)
        self.assertFalse(records[0].is_bugfix)
        self.assertGreater(records[0].insertions, 0)
        self.assertGreater(len(records[0].changes), 0)
        payload = records[0].as_dict()
        self.assertEqual(payload["sha"], self.shas["first"])
        self.assertGreater(payload["files_changed"], 0)

    def test_history_since_and_limit(self) -> None:
        records = self.runner.history(self.repo, since=self.shas["second"])
        self.assertEqual([record.sha for record in records], [self.shas["third"], self.shas["fourth"]])
        # git применяет max-count до --reverse: limit оставляет последние коммиты,
        # но возвращает их в хронологическом порядке.
        limited = self.runner.history(self.repo, limit=2)
        self.assertEqual(len(limited), 2)
        self.assertEqual([record.sha for record in limited], [self.shas["third"], self.shas["fourth"]])

    def test_tree_and_blobs(self) -> None:
        tree = self.runner.tree_files(self.repo, self.shas["fourth"])
        paths = {info.path for info in tree}
        self.assertIn("pkg/core.py", paths)
        self.assertIn("pkg/feature.py", paths)
        core = next(info for info in tree if info.path == "pkg/core.py")
        blobs = self.runner.read_blobs(self.repo, [core.sha, "0" * 40])
        self.assertIn(b"def add", blobs[core.sha])
        self.assertIsNone(blobs["0" * 40])
        self.assertEqual(self.runner.read_blobs(self.repo, []), {})
        self.assertIn(b"def add", self.runner.file_at(self.repo, self.shas["fourth"], "pkg/core.py"))
        self.assertIsNone(self.runner.file_at(self.repo, "badref", "pkg/core.py"))

    def test_patch_history(self) -> None:
        text = self.runner.patch_history(self.repo, "pkg/core.py", limit=5)
        self.assertIn("\x01" + self.shas["second"], text)
        self.assertIn("def clamp", text)

    def test_refs(self) -> None:
        tags = self.runner.tags(self.repo)
        self.assertEqual(tags[0].name, "v1.0")
        self.assertEqual(tags[0].sha, self.shas["second"])
        branches = {branch.name: branch for branch in self.runner.branches(self.repo)}
        self.assertEqual(branches["legacy"].sha, self.shas["first"])
        self.assertEqual(self.runner.resolve_ref(self.repo, "v1.0"), self.shas["second"])
        self.assertIsNone(self.runner.resolve_ref(self.repo, "nope"))
        self.assertEqual(self.runner.parent(self.repo, self.shas["fourth"]), self.shas["third"])
        self.assertIsNone(self.runner.parent(self.repo, self.shas["first"]))

    def test_ancestry(self) -> None:
        self.assertTrue(self.runner.is_ancestor(self.repo, self.shas["first"], self.shas["fourth"]))
        self.assertFalse(self.runner.is_ancestor(self.repo, self.shas["fourth"], self.shas["first"]))

    def test_clone(self) -> None:
        target = self.root / "cloned"
        runner = GitRunner(timeout=60)
        runner.clone(str(self.repo), target)
        self.assertEqual((target / "pkg" / "core.py").exists(), True)
        self.assertEqual(runner.head_sha(target), self.shas["fourth"])

    def test_bugfix_and_path_helpers(self) -> None:
        self.assertTrue(mark_bugfix("fix crash in loader"))
        self.assertTrue(mark_bugfix("Исправление бага"))
        self.assertFalse(mark_bugfix("add feature"))
        self.assertFalse(mark_bugfix("update docs"))
        self.assertTrue(mark_bugfix("hotfix", r"hotfix"))
        self.assertTrue(is_python_path("a/b.py"))
        self.assertTrue(is_python_path("a/b.pyi"))
        self.assertFalse(is_python_path("a/b.js"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
