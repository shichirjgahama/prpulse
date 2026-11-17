"""Замеры полной и инкрементальной индексации для CLI-команды bench."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from projectpulse.core.events import AppError
from projectpulse.core.runtime import Runtime


def _run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
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
        raise AppError(f"git {' '.join(args)}: {result.stderr.strip()}")


def _probe_commit(repo: Path, index: int) -> str:
    """Создаёт изолирующий коммит в клоне, чтобы измерить инкрементальный проход."""
    target = repo / f"projectpulse_bench_probe_{index}.py"
    target.write_text(
        f'"""Технический файл замера {index}."""\n\n\ndef probe_{index}():\n    return {index}\n',
        encoding="utf-8",
    )
    stamp = f"@{int(time.time()) + index} +0000"
    env = {
        "GIT_AUTHOR_NAME": "ProjectPulse Bench",
        "GIT_AUTHOR_EMAIL": "bench@example.invalid",
        "GIT_COMMITTER_NAME": "ProjectPulse Bench",
        "GIT_COMMITTER_EMAIL": "bench@example.invalid",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    _run_git(repo, "add", "--", target.name)
    _run_git(repo, "commit", "-q", "-m", f"fix benchmark probe {index}", env=env)
    return target.name


def _timed(indexer, repo_id: int, mode: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = indexer.index(repo_id, mode=mode, progress=None)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "duration_ms": duration_ms,
        "kind": result.kind,
        "commits_new": result.commits_new,
        "files_parsed": result.files_parsed,
        "findings": result.findings,
        "health": result.health_score,
    }


def benchmark_index(runtime: Runtime, repo_id: int, runs: int = 1) -> dict[str, Any]:
    """Меряет полную и инкрементальную индексацию на временном клоне.

    Клон нужен, чтобы не менять историю исходного репозитория. Перед каждым
    инкрементальным проходом добавляется отдельный пробный коммит.
    """
    source = runtime.store.get_repo(repo_id)
    if not source:
        raise AppError(f"Репозиторий {repo_id} не найден")
    runs = max(1, int(runs))
    workdir = runtime.config.paths.cache_dir / f"bench_{os.getpid()}_{int(time.time())}"
    clone = workdir / "clone"
    workdir.mkdir(parents=True, exist_ok=True)
    bench_repo_id: int | None = None
    try:
        _run_git(Path(source["path"]), "clone", "--quiet", "--no-hardlinks", source["path"], str(clone))
        repo = runtime.indexer.add_repository(clone, name=f"{source['name']} [bench]")
        bench_repo_id = int(repo["id"])

        full_runs = [_timed(runtime.indexer, bench_repo_id, "full") for _ in range(runs)]
        incremental_runs: list[dict[str, Any]] = []
        for index in range(runs):
            _probe_commit(clone, index)
            incremental_runs.append(_timed(runtime.indexer, bench_repo_id, "incremental"))
        no_changes = _timed(runtime.indexer, bench_repo_id, "incremental")
        snapshots = len(runtime.store.list_snapshots(bench_repo_id))

        def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
            durations = sorted(item["duration_ms"] for item in items)
            middle = durations[len(durations) // 2]
            return {
                "duration_ms": middle,
                "min_ms": durations[0],
                "max_ms": durations[-1],
                "runs": items,
            }

        return {
            "repo_id": bench_repo_id,
            "repo": source["name"],
            "runs": runs,
            "full": summary(full_runs),
            "incremental": summary(incremental_runs),
            "incremental_no_changes": {
                "duration_ms": no_changes["duration_ms"],
                "files_parsed": no_changes["files_parsed"],
                "commits_new": no_changes["commits_new"],
            },
            "snapshots": snapshots,
        }
    finally:
        if bench_repo_id is not None:
            runtime.store.delete_repo(bench_repo_id)
        shutil.rmtree(workdir, ignore_errors=True)
