"""Полный демонстрационный прогон: индексация, отчёты, сравнение и исследование."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectpulse.analysis.compare import compare_repos  # noqa: E402
from projectpulse.analysis.research import run_research  # noqa: E402
from projectpulse.core.runtime import build_runtime  # noqa: E402
from projectpulse.report.service import generate_report, write_research  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Демонстрационный прогон ProjectPulse")
    parser.add_argument("--home", default=str(ROOT / "demo_home"))
    parser.add_argument("--reindex", action="store_true", help="Пересобрать индексы заново")
    parser.add_argument("--bench", action="store_true", help="Запустить замеры после отчётов")
    parser.add_argument("--tests", action="store_true", help="Запустить набор тестов")
    args = parser.parse_args(argv)

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    samples = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_samples.py"), "--no-network"],
        capture_output=True,
        text=True,
        check=False,
    )
    if samples.returncode != 0:
        print(samples.stdout)
        print("Демонстрационные репозитории не готовы. Выполните scripts/prepare_samples.py без --no-network.")
        return 1

    config = json.loads((ROOT / "repos.json").read_text(encoding="utf-8"))
    runtime = build_runtime(args.home)
    summary: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "repositories": []}
    try:
        indexed = {}
        for entry in config["repositories"]:
            repo = runtime.ensure_repo(str(ROOT / entry["path"]), name=entry["name"])
            repo_id = int(repo["id"])
            if args.reindex or not runtime.store.latest_run(repo_id):
                result = runtime.indexer.index(repo_id, mode="full")
                print(f"{entry['name']}: {result.summary()}")
            else:
                print(f"{entry['name']}: используется готовый индекс")
            run = runtime.store.latest_run(repo_id)
            health = runtime.store.get_health(int(run["id"])) if run else None
            counts = runtime.store.counts(repo_id)
            summary["repositories"].append(
                {
                    "name": entry["name"],
                    "role": entry["role"],
                    "repo_id": repo_id,
                    "run_id": int(run["id"]) if run else None,
                    "health": (health or {}).get("score"),
                    "health_label": ((health or {}).get("components") or {}).get("label"),
                    "commits": counts["commits"],
                    "files": counts["files"],
                    "authors": counts["authors"],
                    "findings": len(runtime.store.get_findings(int(run["id"]))) if run else 0,
                    "snapshots": len(runtime.store.list_snapshots(repo_id)),
                }
            )
            indexed[entry["role"]] = repo
            for fmt in ("html", "pdf"):
                target = reports / f"{entry['name']}.{fmt}"
                written = generate_report(runtime.store, runtime.config, repo_id, formats=[fmt], out=target)
                print(f"  {fmt.upper()}: {written[fmt]}")

        healthy = indexed.get("healthy")
        problematic = indexed.get("problematic")
        if healthy and problematic:
            comparison = compare_repos(runtime.store, healthy, problematic)
            (reports / "compare.json").write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
            )
            print(f"Сравнение: {comparison['verdict']}")
            research = run_research(runtime.store, healthy, problematic)
            markdown_path, json_path = write_research(research, runtime.config, reports / "research_report")
            print(f"Исследование: {markdown_path}")
            print(f"Данные: {json_path}")
    finally:
        runtime.close()

    (reports / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Сводка: {reports / 'summary.json'}")

    if args.bench:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "benchmark.py"), "--home", args.home, "--simulate"],
            check=False,
        )
    if args.tests:
        separator = ";" if sys.platform == "win32" else ":"
        env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{separator}{ROOT}"}
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=str(ROOT),
            env=env,
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
