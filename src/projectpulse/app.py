"""Командная строка ProjectPulse. Без команды запускается графический интерфейс."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from projectpulse import __version__
from projectpulse.analysis.compare import compare_repos, indicator_delta
from projectpulse.analysis.research import run_research
from projectpulse.core.events import AppError, IndexCancelled, Progress, close_logging
from projectpulse.core.runtime import Runtime, build_runtime, describe_plugins
from projectpulse.core.utils import format_duration_ms
from projectpulse.report.service import generate_report, write_research


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="projectpulse",
        description="ProjectPulse: локальный цифровой двойник программного проекта по Git-репозиторию.",
    )
    parser.add_argument("--home", help="Каталог данных приложения (по умолчанию LOCALAPPDATA/ProjectPulse)")
    parser.add_argument("--version", action="version", version=f"ProjectPulse {__version__}")
    parser.add_argument("--no-plugins", action="store_true", help="Не загружать внешние плагины")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="Открыть графический интерфейс")
    gui.set_defaults(handler=_cmd_gui)

    add = sub.add_parser("add", help="Добавить репозиторий без индексации")
    add.add_argument("--repo", required=True, help="Путь к git-репозиторию")
    add.add_argument("--name", help="Отображаемое имя")
    add.set_defaults(handler=_cmd_add)

    repos = sub.add_parser("repos", help="Список добавленных репозиториев")
    repos.add_argument("--json", action="store_true")
    repos.set_defaults(handler=_cmd_repos)

    index = sub.add_parser("index", help="Проиндексировать репозиторий")
    index.add_argument("--repo", required=True, help="Путь к git-репозиторию")
    index.add_argument("--name", help="Отображаемое имя при первом добавлении")
    index.add_argument("--mode", choices=["full", "incremental", "rebuild"], default="incremental")
    index.add_argument("--json", action="store_true", help="Печать результата в JSON")
    index.add_argument("--quiet", action="store_true", help="Без прогресса")
    index.set_defaults(handler=_cmd_index)

    report = sub.add_parser("report", help="Сформировать HTML и/или PDF отчёт")
    report.add_argument("--repo", required=True, help="Путь или имя репозитория")
    report.add_argument("--format", default="html", help="html, pdf или список через запятую")
    report.add_argument("--out", help="Файл или каталог для отчёта")
    report.add_argument("--json", action="store_true")
    report.set_defaults(handler=_cmd_report)

    research = sub.add_parser("research", help="Мини-исследование по двум репозиториям")
    research.add_argument("--healthy", required=True, help="Путь к здоровому репозиторию")
    research.add_argument("--problematic", required=True, help="Путь к проблемному репозиторию")
    research.add_argument("--out", help="Файл .md/.json или каталог")
    research.add_argument("--no-index", action="store_true", help="Не запускать индексацию автоматически")
    research.add_argument("--json", action="store_true")
    research.set_defaults(handler=_cmd_research)

    compare = sub.add_parser("compare", help="Сравнить два репозитория")
    compare.add_argument("--a", required=True, help="Путь или имя первого репозитория")
    compare.add_argument("--b", required=True, help="Путь или имя второго репозитория")
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(handler=_cmd_compare)

    plugins = sub.add_parser("plugins", help="Показать метрики, правила и плагины")
    plugins.add_argument("--json", action="store_true")
    plugins.set_defaults(handler=_cmd_plugins)

    bench = sub.add_parser("bench", help="Замер полной и инкрементальной индексации")
    bench.add_argument("--repo", required=True)
    bench.add_argument("--runs", type=int, default=1)
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(handler=_cmd_bench)
    return parser


class _ConsoleProgress:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self.last_phase = ""

    def __call__(self, event: Progress) -> None:
        if self.quiet:
            return
        if event.phase != self.last_phase:
            self.last_phase = event.phase
            sys.stdout.write("\n")
        if event.total > 0:
            width = 28
            filled = int(width * event.fraction)
            bar = "#" * filled + "." * (width - filled)
            sys.stdout.write(f"\r[{bar}] {event.current}/{event.total} {event.message[:58]:<58}")
        else:
            sys.stdout.write(f"\r{event.message[:90]:<90}")
        sys.stdout.flush()

    def finish(self) -> None:
        if not self.quiet:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _repo_by_value(runtime: Runtime, value: str) -> dict:
    repo = runtime.find_repo(value)
    if repo is None:
        raise AppError(f"Репозиторий не найден в базе: {value}. Сначала выполните index --repo <путь>")
    return repo


def _ensure_ready(runtime: Runtime, value: str, name: str | None = None) -> dict:
    repo = runtime.ensure_repo(value, name=name)
    if not runtime.store.latest_run(int(repo["id"])):
        progress = _ConsoleProgress()
        try:
            runtime.indexer.index(int(repo["id"]), mode="incremental", progress=progress)
        finally:
            progress.finish()
        repo = runtime.store.get_repo(int(repo["id"])) or repo
    return repo


def _cmd_gui(args, runtime: Runtime) -> int:
    from projectpulse.ui.app import run_gui

    return run_gui(runtime)


def _cmd_add(args, runtime: Runtime) -> int:
    repo = runtime.indexer.add_repository(args.repo, name=args.name)
    print(json.dumps(repo, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_repos(args, runtime: Runtime) -> int:
    repos = runtime.store.list_repos()
    if args.json:
        print(json.dumps(repos, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not repos:
        print("Репозитории не добавлены. Используйте projectpulse add --repo <путь>.")
        return 0
    print(f"{'id':>3}  {'имя':<28} {'HEAD':<12} {'коммитов':>9} {'файлов':>7}  путь")
    for repo in repos:
        print(
            f"{repo['id']:>3}  {repo['name'][:28]:<28} {(repo.get('head_sha') or '-')[:12]:<12} "
            f"{repo.get('commits_total', 0):>9} {repo.get('files_total', 0):>7}  {repo['path']}"
        )
    return 0


def _cmd_index(args, runtime: Runtime) -> int:
    repo = runtime.ensure_repo(args.repo, name=args.name)
    progress = _ConsoleProgress(args.quiet)
    try:
        result = runtime.indexer.index(int(repo["id"]), mode=args.mode, progress=progress)
    except IndexCancelled:
        print("\nИндексация отменена")
        return 2
    finally:
        progress.finish()
    if args.json:
        payload = {
            "repo_id": result.repo_id,
            "run_id": result.run_id,
            "kind": result.kind,
            "duration_ms": result.duration_ms,
            "commits_seen": result.commits_seen,
            "commits_new": result.commits_new,
            "files_parsed": result.files_parsed,
            "files_skipped": result.files_skipped,
            "snapshots": result.snapshots,
            "health": result.health_score,
            "findings": result.findings,
            "warnings": result.warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result.summary())
        if result.warnings:
            for warning in result.warnings:
                print(f"  предупреждение: {warning}")
    return 0


def _cmd_report(args, runtime: Runtime) -> int:
    repo = _repo_by_value(runtime, args.repo)
    formats = [part.strip() for part in args.format.split(",") if part.strip()]
    written = generate_report(runtime.store, runtime.config, int(repo["id"]), formats=formats, out=args.out)
    if args.json:
        print(json.dumps(written, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for fmt, path in written.items():
            print(f"{fmt.upper()}: {path}")
    return 0


def _cmd_research(args, runtime: Runtime) -> int:
    if args.no_index:
        healthy = _repo_by_value(runtime, args.healthy)
        problematic = _repo_by_value(runtime, args.problematic)
    else:
        healthy = _ensure_ready(runtime, args.healthy)
        problematic = _ensure_ready(runtime, args.problematic)
    result = run_research(runtime.store, healthy, problematic)
    markdown_path, json_path = write_research(result, runtime.config, args.out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Гипотеза: {result['hypothesis']}")
        for key in ("healthy", "problematic"):
            repo = result[key]
            print(f"\n{repo['name']}: коммитов {repo['commits']}, недель {repo['weeks']}, авторов {repo['authors']}")
            for item in repo["correlations"]:
                print(
                    f"  {item['name']}: Пирсон {item['pearson']:+.3f}, "
                    f"Спирмен {item['spearman']:+.3f}, p={item['p_value']:.4f}, n={item['n']}"
                )
        print(f"\nMarkdown: {markdown_path}")
        print(f"JSON: {json_path}")
    return 0


def _cmd_compare(args, runtime: Runtime) -> int:
    repo_a = _ensure_ready(runtime, args.a)
    repo_b = _ensure_ready(runtime, args.b)
    result = compare_repos(runtime.store, repo_a, repo_b)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"{'Показатель':<34} {repo_a['name'][:18]:>18} {repo_b['name'][:18]:>18}  лучше")
    for row in result["indicators"]:
        better = {"a": repo_a["name"], "b": repo_b["name"], "tie": "равно"}[row["better"]]
        print(f"{row['title']:<34} {row['a']:>18.2f} {row['b']:>18.2f}  {better.strip()}")
    print()
    print(result["verdict"])
    return 0


def _cmd_plugins(args, runtime: Runtime) -> int:
    payload = describe_plugins(runtime)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Метрик: {len(payload['metrics'])}, правил: {len(payload['rules'])}")
    for item in payload["metrics"]:
        mark = "builtin" if item["builtin"] else item["source"]
        print(f"  метрика  {item['name']:<28} {mark}")
    for item in payload["rules"]:
        mark = "builtin" if item["builtin"] else item["source"]
        print(f"  правило  {item['name']:<28} {mark}")
    if payload["loaded"]:
        print("\nЗагруженные плагины:")
        for plugin in payload["loaded"]:
            print(f"  {plugin['source']} ({len(plugin['items'])} регистраций)")
    return 0


def _cmd_bench(args, runtime: Runtime) -> int:
    from projectpulse.scripts_bench import benchmark_index

    repo = _ensure_ready(runtime, args.repo)
    result = benchmark_index(runtime, int(repo["id"]), runs=max(1, args.runs))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Репозиторий: {repo['name']}")
        for key in ("full", "incremental", "incremental_no_changes"):
            item = result.get(key)
            if item:
                print(f"  {key:<24} {format_duration_ms(item['duration_ms'])} ({item['duration_ms']} мс)")
        print(f"  срезов графа: {result['snapshots']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    runtime: Runtime | None = None
    if not getattr(args, "command", None):
        args.command = "gui"
        args.handler = _cmd_gui
    try:
        runtime = build_runtime(args.home, with_plugins=not args.no_plugins)
        return int(args.handler(args, runtime) or 0)
    except AppError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано пользователем", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI не должен показывать трассировку по умолчанию
        print(f"Непредвиденная ошибка: {exc}", file=sys.stderr)
        if __debug__:
            import traceback

            traceback.print_exc()
        return 1
    finally:
        if runtime is not None:
            try:
                runtime.database.close()
            except Exception:  # noqa: BLE001 - закрытие не должно маскировать результат
                pass
            close_logging()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
