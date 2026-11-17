"""Микрозамеры двух оптимизаций: пакетное чтение blob и кэш разбора по SHA"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectpulse.analysis.parser import analyze_bytes  # noqa: E402
from projectpulse.core.runtime import build_runtime  # noqa: E402


def milliseconds(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Микрозамеры ProjectPulse")
    parser.add_argument("--home", default=str(ROOT / "demo_home"))
    parser.add_argument("--repo", default="samples/django-extensions")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", default=str(ROOT / "reports" / "microbench.json"))
    args = parser.parse_args(argv)

    runtime = build_runtime(args.home)
    repo_path = (ROOT / args.repo).resolve()
    result: dict = {"repo": str(repo_path), "limit": args.limit}
    try:
        repo = runtime.ensure_repo(str(repo_path))
        head = runtime.git.head_sha(repo_path)
        tree = [item for item in runtime.git.tree_files(repo_path, head) if item.path.endswith((".py", ".pyi"))]
        selected = tree[: args.limit]
        result["python_files_total"] = len(tree)
        result["python_files_measured"] = len(selected)

        started = time.perf_counter()
        blobs = runtime.git.read_blobs(repo_path, [item.sha for item in selected])
        batch_ms = milliseconds(started)

        started = time.perf_counter()
        sequential: dict[str, bytes | None] = {}
        for item in selected:
            sequential[item.sha] = runtime.git.file_at(repo_path, head, item.path)
        sequential_ms = milliseconds(started)
        result["blob_read"] = {
            "batch_ms": batch_ms,
            "sequential_ms": sequential_ms,
            "speedup": round(sequential_ms / max(batch_ms, 1), 2),
            "files": len(selected),
        }

        parsed = {}
        started = time.perf_counter()
        for item in selected:
            payload = blobs.get(item.sha)
            if payload is not None:
                parsed[item.sha] = analyze_bytes(item.path, payload)
        cold_ms = milliseconds(started)

        cache = {item.sha: analyze_bytes(item.path, blobs[item.sha]) for item in selected if blobs.get(item.sha) is not None}
        loops = 1000
        started_ns = time.perf_counter_ns()
        for _ in range(loops):
            for item in selected:
                _ = cache.get(item.sha)
        warm_lookup_us = (time.perf_counter_ns() - started_ns) / 1000.0 / loops
        warm_pass_ms = warm_lookup_us * len(cache) / 1000.0
        result["parse_cache"] = {
            "cold_parse_ms": cold_ms,
            "warm_lookup_us": round(warm_lookup_us, 3),
            "warm_pass_ms": round(warm_pass_ms, 3),
            "files": len(cache),
            "speedup": round(cold_ms / max(warm_pass_ms, 0.001), 1),
            "bytes": sum(len(blobs[item.sha] or b"") for item in selected),
        }
        result["repo_id"] = int(repo["id"])
    finally:
        runtime.close()

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"JSON: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
