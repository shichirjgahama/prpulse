"""Клонирование и фиксация демонстрационных репозиториев из repos.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def current_head(repo: Path) -> str | None:
    result = run_git(repo, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def prepare(entry: dict, no_network: bool = False) -> dict:
    path = ROOT / entry["path"]
    commit = entry["commit"]
    if not (path / ".git").exists():
        if no_network:
            return {"name": entry["name"], "status": "missing", "path": str(path)}
        path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--quiet", entry["url"], str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return {"name": entry["name"], "status": "clone_failed", "error": result.stderr.strip()}
    head = current_head(path)
    if head != commit:
        result = run_git(path, "checkout", "--quiet", commit)
        if result.returncode != 0:
            return {"name": entry["name"], "status": "checkout_failed", "error": result.stderr.strip()}
        head = current_head(path)
    count = run_git(path, "rev-list", "--count", "HEAD").stdout.strip()
    return {"name": entry["name"], "status": "ready", "commit": head, "commits": count, "path": str(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка демонстрационных репозиториев")
    parser.add_argument("--no-network", action="store_true", help="Только проверить локальные копии")
    args = parser.parse_args(argv)
    config = json.loads((ROOT / "repos.json").read_text(encoding="utf-8"))
    failed = False
    for entry in config["repositories"]:
        result = prepare(entry, args.no_network)
        print(json.dumps(result, ensure_ascii=False))
        failed = failed or result["status"] != "ready"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
