"""Общие помощники тестов: временные git-репозитории и данные анализа."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from projectpulse.analysis.context import RepoContext
from projectpulse.analysis.graph import build_entity_graph, build_file_graph
from projectpulse.analysis.parser import analyze_source
from projectpulse.core.config import AppConfig, Thresholds
from projectpulse.core.runtime import build_runtime


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env or {})
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result


def write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(
    repo: Path,
    message: str,
    ts: int,
    author: tuple[str, str] = ("Alice", "alice@example.com"),
    paths: Iterable[str] = (),
) -> str:
    if paths:
        run_git(repo, "add", "--", *paths)
    else:
        run_git(repo, "add", "-A")
    env = {
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": author[0],
        "GIT_COMMITTER_EMAIL": author[1],
        "GIT_AUTHOR_DATE": f"@{ts} +0000",
        "GIT_COMMITTER_DATE": f"@{ts} +0000",
    }
    run_git(repo, "commit", "-q", "-m", message, env=env)
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "config", "user.email", "test@example.com")


CORE_V1 = '''"""Core helpers."""

def add(a, b):
    """Сложение с ветвлением."""
    if a > b:
        return a - b
    return a + b


def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0
'''


CORE_V2 = '''"""Core helpers."""

def add(a, b):
    """Сложение с ветвлением."""
    if a > b:
        return a - b
    return a + b


def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0


def clamp(value, low, high):
    return max(low, min(high, value))
'''


def make_sample_repo(path: Path) -> dict[str, str]:
    """Создаёт репозиторий с историей, циклом, тегом и веткой."""
    init_git(path)
    write(path, "pkg/__init__.py", '"""Package."""\n\nfrom .core import add\n\n__all__ = ["add"]\n')
    write(path, "pkg/core.py", CORE_V1)
    write(path, "pkg/util.py", '"""Utilities."""\n\nfrom .core import add\n\n\ndef twice(value):\n    return add(value, value)\n')
    write(path, "pkg/a.py", '"""Cycle A."""\n\nfrom .b import beta\n\n\ndef alpha(value):\n    return beta(value)\n')
    write(path, "pkg/b.py", '"""Cycle B."""\n\nfrom .a import alpha\n\n\ndef beta(value):\n    return alpha(value) if value > 100 else value\n')
    first = commit(path, "initial import", 1704099600, ("Alice", "alice@example.com"))

    write(path, "pkg/core.py", CORE_V2)
    write(
        path,
        "pkg/complex.py",
        '''"""Complex code."""

def classify(value):
    if value < 0:
        return "neg"
    elif value == 0:
        return "zero"
    elif value < 10:
        return "small"
    return "large"


def nested(items):
    total = 0
    for item in items:
        if item and item > 0:
            total += item
    return total
''',
    )
    second = commit(path, "fix crash in core and add complex module", 1705309200, ("Bob", "bob@example.com"))

    write(
        path,
        "pkg/feature.py",
        '''"""Feature module."""

from .util import twice


def run(values):
    result = []
    for value in values:
        if value % 2 == 0:
            result.append(twice(value))
        else:
            result.append(value)
    return result
''',
    )
    third = commit(path, "add feature runner", 1707040800, ("Alice", "alice@example.com"))

    write(path, "pkg/util.py", '"""Utilities."""\n\nfrom .core import add, clamp\n\n\ndef twice(value):\n    return add(value, value)\n\n\ndef bounded(value):\n    return clamp(value, 0, 100)\n')
    fourth = commit(path, "fix bounded utility", 1709632800, ("Carol", "carol@example.com"))

    run_git(path, "tag", "v1.0", second)
    run_git(path, "branch", "legacy", first)
    return {"first": first, "second": second, "third": third, "fourth": fourth}


def append_commit(repo: Path, ts: int = 1712239200) -> str:
    write(repo, "pkg/newmod.py", '"""New module."""\n\n\ndef answer():\n    return 42\n')
    write(repo, "pkg/feature.py", '"""Feature module."""\n\nfrom .util import twice\nfrom .newmod import answer\n\n\ndef run(values):\n    result = [answer()]\n    for value in values:\n        if value % 2 == 0:\n            result.append(twice(value))\n        else:\n            result.append(value)\n    return result\n')
    return commit(repo, "fix feature and add new module", ts, ("Bob", "bob@example.com"))


def make_runtime(home: Path):
    return build_runtime(home, with_plugins=False)


def make_context(
    sources: dict[str, str],
    commits: list[dict] | None = None,
    commit_files: list[dict] | None = None,
    thresholds: Thresholds | None = None,
    history_metrics: dict | None = None,
) -> RepoContext:
    parsed = {path: analyze_source(path, text) for path, text in sources.items()}
    files = [item.file_row() for item in parsed.values()]
    entities: list[dict] = []
    refs: list[dict] = []
    imports: list[dict] = []
    for item in parsed.values():
        entities.extend(entity.as_dict() for entity in item.entities)
        refs.extend(ref.as_dict() for ref in item.refs)
        imports.extend(imp.as_dict() for imp in item.imports)
    file_graph = build_file_graph(files, imports)
    entity_graph = build_entity_graph(files, entities, refs)
    commits = commits or []
    commit_files = commit_files or []
    as_of = max((int(row["ts"]) for row in commits), default=0)
    return RepoContext(
        repo={"id": 1, "name": "fixture"},
        as_of=as_of,
        files=files,
        commits=commits,
        commit_files=commit_files,
        entities=entities,
        refs=refs,
        imports=imports,
        file_graph=file_graph,
        entity_graph=entity_graph,
        thresholds=thresholds or Thresholds(),
        history_metrics=history_metrics or {},
    )


class TempDirMixin:
    _tempdir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._tempdir = tempfile.TemporaryDirectory(prefix="pp_tests_")
        cls.root = Path(cls._tempdir.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tempdir.cleanup()
