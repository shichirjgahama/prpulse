"""Конфигурация приложения и пороги правил риска."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "ProjectPulse"


def default_home() -> Path:
    override = os.environ.get("PROJECTPULSE_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


@dataclass(frozen=True)
class Paths:
    home: Path
    db_path: Path
    log_path: Path
    reports_dir: Path
    plugins_dir: Path
    cache_dir: Path


@dataclass
class Thresholds:
    """Пороги правил и параметры анализа. Все значения воспроизводимы."""

    hotspot_complexity_percentile: float = 0.90
    hotspot_churn_percentile: float = 0.75
    hotspot_min_complexity: int = 8
    bus_factor_commits_min: int = 10
    ownership_share_high: float = 0.85
    ownership_commits_min: int = 5
    churn_spike_z: float = 2.5
    churn_spike_recent_weeks: int = 12
    churn_window_weeks: int = 26
    churn_recent_weeks: int = 4
    volatility_ratio: float = 1.5
    volatility_min: float = 0.45
    fix_pressure_recent_days: int = 45
    fix_pressure_baseline_days: int = 180
    fix_pressure_growth: float = 0.5
    fix_pressure_critical_growth: float = 2.0
    fix_pressure_critical_recent: float = 0.5
    ownership_drift_threshold: float = 0.35
    api_volatility_threshold: float = 0.40
    api_min_public_changes: int = 3
    god_module_fan_in: int = 5
    god_module_fan_out: int = 5
    god_module_loc: int = 300
    cycle_min_nodes: int = 2
    churn_recent_days: int = 90
    bugfix_pattern: str = (
        r"(?i)\b(fix|fixes|fixed|bug|bugfix|hotfix|issue|crash|regression|"
        r"исправ|почин|баг)\w*"
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Thresholds":
        known = {item.name for item in fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        return cls(**payload)


@dataclass
class AppConfig:
    paths: Paths
    thresholds: Thresholds = field(default_factory=Thresholds)
    max_file_bytes: int = 1_500_000
    max_snapshot_tags: int = 8
    max_snapshot_branches: int = 5
    max_snapshot_files: int = 2500
    ivi_files_limit: int = 24
    ivi_commits_limit: int = 20
    history_timeout: int = 180
    git_timeout: int = 120
    log_level: int = 20

    @classmethod
    def load(cls, home: Path | str | None = None) -> "AppConfig":
        base = Path(home).expanduser() if home else default_home()
        paths = Paths(
            home=base,
            db_path=base / "projectpulse.db",
            log_path=base / "projectpulse.log",
            reports_dir=base / "reports",
            plugins_dir=base / "plugins",
            cache_dir=base / "cache",
        )
        for directory in (paths.home, paths.reports_dir, paths.plugins_dir, paths.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)

        thresholds = Thresholds()
        override = base / "thresholds.json"
        if override.exists():
            try:
                thresholds = Thresholds.from_dict(json.loads(override.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                thresholds = Thresholds()

        return cls(paths=paths, thresholds=thresholds)


def packaged_plugins_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "plugins"


def project_plugins_dir() -> Path:
    """Каталог plugins рядом с репозиторием проекта (для разработки)."""
    return Path(__file__).resolve().parents[3] / "plugins"
