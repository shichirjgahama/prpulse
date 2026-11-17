"""Общие утилиты: идентификаторы, статистика, работа с датами."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence


def stable_id(*parts: object, length: int = 16) -> str:
    """Детерминированный идентификатор из набора частей."""
    payload = "\x1f".join(str(p) for p in parts).encode("utf-8", "replace")
    return hashlib.sha1(payload).hexdigest()[:length]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


SUPPORT_DIRS = {
    ".github",
    "benchmark",
    "benchmarks",
    "ci",
    "doc",
    "docs",
    "downstream",
    "example",
    "examples",
    "sample",
    "samples",
    "script",
    "scripts",
    "test",
    "tests",
    "testing",
}


def is_support_path(path: str) -> bool:
    """Тесты, примеры, документация и служебные скрипты не являются продуктовым кодом."""
    clean = path.replace("\\", "/").strip("/")
    if not clean:
        return False
    parts = [part.lower() for part in clean.split("/")]
    if any(part in SUPPORT_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")


def is_support_module(name: str) -> bool:
    return name.strip().lower() in SUPPORT_DIRS


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Линейная интерполяция перцентиля. fraction в диапазоне 0..1."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    position = clamp(fraction, 0.0, 1.0) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(max(0.0, variance))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def entropy(counts: Iterable[float]) -> float:
    """Энтропия Шеннона в битах."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    result = 0.0
    for count in counts:
        if count > 0:
            share = count / total
            result -= share * math.log2(share)
    return result


def normalized_entropy(counts: Iterable[float]) -> float:
    values = [float(c) for c in counts if c > 0]
    if len(values) <= 1:
        return 0.0
    return entropy(values) / math.log2(len(values))


def human_bytes(size: float) -> str:
    units = ["Б", "КБ", "МБ", "ГБ"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def format_duration_ms(value: float | int | None) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if amount < 1000:
        return f"{amount:.0f} мс"
    if amount < 60_000:
        return f"{amount / 1000:.2f} с"
    minutes = amount / 60_000
    if minutes < 60:
        return f"{minutes:.1f} мин"
    return f"{minutes / 60:.2f} ч"


def truncate(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def week_start(timestamp: int) -> date:
    """Понедельник ISO-недели для unix timestamp (UTC)."""
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
    return moment - timedelta(days=moment.weekday())


def week_key(timestamp: int) -> str:
    start = week_start(timestamp)
    return start.isoformat()


def weeks_between(start: date, end: date) -> list[date]:
    if end < start:
        return []
    result: list[date] = []
    cursor = start
    while cursor <= end:
        result.append(cursor)
        cursor += timedelta(days=7)
    return result


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def day_span(start: date, end: date) -> int:
    return max(1, (end - start).days + 1)


def recency_weight(timestamp: int, as_of: int, half_life_days: float = 180.0) -> float:
    if half_life_days <= 0:
        return 1.0
    age_days = max(0.0, (as_of - timestamp) / 86400.0)
    return 0.5 ** (age_days / half_life_days)


def round_value(value: float, digits: int = 4) -> float:
    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def percentage(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def sort_dicts(rows: Iterable[dict], key: str, reverse: bool = False) -> list[dict]:
    return sorted(rows, key=lambda row: row.get(key), reverse=reverse)
