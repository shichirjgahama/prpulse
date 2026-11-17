"""Сервис формирования отчётов: имена файлов, HTML и PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from projectpulse.core.config import AppConfig
from projectpulse.core.events import ReportError
from projectpulse.core.utils import iso
from projectpulse.report.builder import ReportData, build_report_data
from projectpulse.report.html import build_html
from projectpulse.report.pdf import write_pdf
from projectpulse.storage.db import Store


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "repo"


def report_basename(data: ReportData) -> str:
    run_id = data.run.get("id", 0)
    stamp = iso().replace(":", "").replace("-", "").replace("+", "_")[:15]
    return f"projectpulse_{safe_name(data.repo['name'])}_run{run_id}_{stamp}"


def _resolve_targets(
    formats: Iterable[str],
    out: Path | str | None,
    config: AppConfig,
    basename: str,
) -> dict[str, Path]:
    requested = [fmt.strip().lower() for fmt in formats if fmt.strip()]
    if not requested:
        requested = ["html"]
    targets: dict[str, Path] = {}
    if out is not None:
        out_path = Path(out).expanduser()
        suffix = out_path.suffix.lower()
        if suffix in {".html", ".htm", ".pdf"} and len(requested) == 1:
            fmt = "pdf" if suffix == ".pdf" else "html"
            targets[fmt] = out_path
            return targets
        if out_path.exists() and out_path.is_file():
            raise ReportError("Для нескольких форматов укажите каталог, а не файл")
        directory = out_path
    else:
        directory = config.paths.reports_dir / safe_name(basename)
    directory.mkdir(parents=True, exist_ok=True)
    for fmt in requested:
        if fmt in {"html", "htm"}:
            targets["html"] = directory / f"{basename}.html"
        elif fmt == "pdf":
            targets["pdf"] = directory / f"{basename}.pdf"
        else:
            raise ReportError(f"Неизвестный формат отчёта: {fmt}")
    return targets


def write_html(data: ReportData, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_html(data), encoding="utf-8")
    return target


def generate_report(
    store: Store,
    config: AppConfig,
    repo_id: int,
    formats: Iterable[str] = ("html",),
    out: Path | str | None = None,
) -> dict[str, str]:
    data = build_report_data(store, repo_id, config)
    basename = report_basename(data)
    targets = _resolve_targets(formats, out, config, basename)
    written: dict[str, str] = {}
    for fmt, path in targets.items():
        if fmt == "html":
            write_html(data, path)
        elif fmt == "pdf":
            write_pdf(data, path)
        else:  # pragma: no cover - защита от расширения списка
            raise ReportError(f"Неизвестный формат: {fmt}")
        written[fmt] = str(path)
    return written


def research_to_markdown(result: dict) -> str:
    from projectpulse.analysis.research import research_markdown

    return research_markdown(result)


def write_research(result: dict, config: AppConfig, out: Path | str | None = None) -> tuple[Path, Path]:
    base = Path(out).expanduser() if out else config.paths.reports_dir / "research"
    if base.suffix.lower() in {".md", ".json"}:
        markdown_path = base.with_suffix(".md")
        json_path = base.with_suffix(".json")
    else:
        base.mkdir(parents=True, exist_ok=True)
        markdown_path = base / "research_report.md"
        json_path = base / "research_report.json"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(research_to_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return markdown_path, json_path
