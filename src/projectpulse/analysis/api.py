"""Исторический анализ публичного API по патчам git."""

from __future__ import annotations

import re
from dataclasses import dataclass

from projectpulse.core.utils import recency_weight

_PUBLIC_DEF_RE = re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")


@dataclass(frozen=True)
class ApiChange:
    sha: str
    ts: int
    public_names: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.public_names)


def parse_patch_history(text: str) -> list[ApiChange]:
    result: list[ApiChange] = []
    current_sha = ""
    current_ts = 0
    names: set[str] = set()

    def flush() -> None:
        nonlocal names
        if current_sha:
            result.append(ApiChange(sha=current_sha, ts=current_ts, public_names=tuple(sorted(names))))
        names = set()

    for line in text.splitlines():
        if line.startswith("\x01"):
            flush()
            header = line[1:]
            parts = header.split("\x1f", 1)
            current_sha = parts[0].strip()
            try:
                current_ts = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                current_ts = 0
            continue
        if not current_sha:
            continue
        match = _PUBLIC_DEF_RE.match(line)
        if match:
            name = match.group(1)
            if not name.startswith("_"):
                names.add(name)
    flush()
    return result


def interface_volatility(
    patch_text: str,
    as_of: int,
    half_life_days: float = 180.0,
) -> dict:
    changes = parse_patch_history(patch_text)
    weighted_total = 0.0
    weighted_changed = 0.0
    public_changes = 0
    public_names: set[str] = set()
    for change in changes:
        weight = recency_weight(change.ts, as_of, half_life_days) if change.ts else 1.0
        weighted_total += weight
        if change.changed:
            weighted_changed += weight
            public_changes += 1
            public_names.update(change.public_names)
    value = weighted_changed / weighted_total if weighted_total > 0 else 0.0
    return {
        "value": round(value, 4),
        "commits_considered": len(changes),
        "public_change_commits": public_changes,
        "public_names": sorted(public_names),
    }
