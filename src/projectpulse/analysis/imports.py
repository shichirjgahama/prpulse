"""Разрешение импортов Python в файлы репозитория."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Sequence

from projectpulse.analysis.parser import ImportRecord


def _dotted(path: str) -> list[str]:
    pure = PurePosixPath(path)
    parts = list(pure.parts)
    if not parts:
        return []
    filename = parts[-1]
    if filename.endswith(".pyi"):
        stem = filename[:-4]
    elif filename.endswith(".py"):
        stem = filename[:-3]
    else:
        stem = filename
    if stem != "__init__":
        parts[-1] = stem
    else:
        parts = parts[:-1]
    return parts


def module_names(path: str) -> set[str]:
    parts = _dotted(path)
    if not parts:
        return set()
    names = {".".join(parts)}
    if len(parts) > 1 and parts[0] in {"src", "lib", "app"}:
        names.add(".".join(parts[1:]))
    return names


@dataclass(frozen=True)
class ResolvedImport:
    source: str
    target: str


class ModuleIndex:
    """Карта модулей, поддерживает src-layout и относительные импорты."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths = sorted({p.replace("\\", "/") for p in paths})
        self.by_module: dict[str, str] = {}
        for path in self.paths:
            for name in module_names(path):
                existing = self.by_module.get(name)
                if existing is None:
                    self.by_module[name] = path
                else:
                    # Детерминированный выбор: короче путь, затем лексикографически.
                    if (path.count("/"), path) < (existing.count("/"), existing):
                        self.by_module[name] = path

    @staticmethod
    def _package_parts(path: str) -> list[str]:
        parts = _dotted(path)
        if path.replace("\\", "/").endswith("__init__.py"):
            return parts
        return parts[:-1]

    def resolve(self, record: ImportRecord | dict) -> list[str]:
        if isinstance(record, dict):
            path = record.get("path", "")
            module = record.get("module")
            level = int(record.get("level") or 0)
            names_raw = record.get("names") or ""
        else:
            path = record.path
            module = record.module
            level = record.level
            names_raw = record.names or ""
        names = [name for name in names_raw.split(",") if name]

        candidates: list[str] = []
        if level > 0:
            package = self._package_parts(path)
            up = level - 1
            if up > len(package):
                return []
            base = package[: len(package) - up] if up else package
            if module:
                base = base + module.split(".")
            if names:
                candidates.extend(".".join(base + [name]) for name in names)
            candidates.append(".".join(base))
        else:
            if not module:
                return []
            candidates.append(module)
            if names:
                candidates.extend(f"{module}.{name}" for name in names)

        targets: list[str] = []
        for candidate in candidates:
            target = self.by_module.get(candidate)
            if target and target != path and target not in targets:
                targets.append(target)
        return targets

    def resolve_all(self, records: Sequence[ImportRecord | dict]) -> list[ResolvedImport]:
        result: list[ResolvedImport] = []
        for record in records:
            path = record["path"] if isinstance(record, dict) else record.path
            for target in self.resolve(record):
                result.append(ResolvedImport(source=path, target=target))
        return result
