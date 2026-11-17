"""cProfile полного или инкрементального прохода индексатора."""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from projectpulse.core.runtime import build_runtime  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Профилирование индексации ProjectPulse")
    parser.add_argument("--home", default=str(ROOT / "demo_home"))
    parser.add_argument("--repo", default="samples/django-extensions")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--out", default=str(ROOT / "reports" / "profile_full.prof"))
    parser.add_argument("--text", default=str(ROOT / "reports" / "profile_full.txt"))
    args = parser.parse_args(argv)

    runtime = build_runtime(args.home)
    try:
        repo = runtime.ensure_repo(str((ROOT / args.repo).resolve()))
        profile = cProfile.Profile()
        profile.enable()
        result = runtime.indexer.index(int(repo["id"]), mode=args.mode)
        profile.disable()
        print(result.summary())
    finally:
        runtime.close()

    prof_path = Path(args.out)
    prof_path.parent.mkdir(parents=True, exist_ok=True)
    profile.dump_stats(str(prof_path))
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).sort_stats("cumulative")
    stats.print_stats(40)
    text = stream.getvalue()
    Path(args.text).write_text(text, encoding="utf-8")
    print(text[:12000])
    print(f"Профиль: {prof_path}")
    print(f"Отчёт: {args.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
