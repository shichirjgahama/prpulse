"""Замер полной, инкрементальной и повторной индексации демонстрационных репозиториев."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectpulse.core.runtime import build_runtime  # noqa: E402
from projectpulse.scripts_bench import benchmark_index  # noqa: E402


def timed(runtime, repo_id: int, mode: str) -> dict:
    started = time.perf_counter()
    result = runtime.indexer.index(repo_id, mode=mode)
    return {
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "kind": result.kind,
        "commits_new": result.commits_new,
        "files_parsed": result.files_parsed,
        "findings": result.findings,
        "health": result.health_score,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Замер индексации ProjectPulse")
    parser.add_argument("--home", default=str(ROOT / "demo_home"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "benchmark.json"))
    parser.add_argument("--simulate", action="store_true", help="Добавить замер с пробным коммитом в клоне")
    parser.add_argument("--skip-full", action="store_true", help="Не повторять полную индексацию")
    args = parser.parse_args(argv)

    runtime = build_runtime(args.home)
    config = json.loads((ROOT / "repos.json").read_text(encoding="utf-8"))
    payload: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "repositories": []}
    try:
        for entry in config["repositories"]:
            repo = runtime.ensure_repo(str(ROOT / entry["path"]), name=entry["name"])
            repo_id = int(repo["id"])
            record = {"name": entry["name"], "role": entry["role"], "repo_id": repo_id}
            if not args.skip_full:
                record["full"] = timed(runtime, repo_id, "full")
            record["incremental_no_changes"] = timed(runtime, repo_id, "incremental")
            if args.simulate:
                record["simulated"] = benchmark_index(runtime, repo_id, runs=1)
            payload["repositories"].append(record)
            print(json.dumps(record, ensure_ascii=False))
    finally:
        runtime.close()

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"JSON: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
