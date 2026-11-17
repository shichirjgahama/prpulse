"""Плагинная расширяемость: DI-контейнер, реестры метрик и правил."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

logger = logging.getLogger("projectpulse.plugins")

METRIC_ENTRY_POINT = "projectpulse.metrics"
RULE_ENTRY_POINT = "projectpulse.rules"


class PluginError(Exception):
    pass


class ServiceContainer:
    """Минимальный DI-контейнер: регистрация по имени и разрешение зависимостей."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def require(self, name: str) -> Any:
        if name not in self._services:
            raise PluginError(f"Сервис не зарегистрирован: {name}")
        return self._services[name]

    def names(self) -> list[str]:
        return sorted(self._services)


@dataclass(frozen=True)
class PluginInfo:
    kind: str
    name: str
    source: str
    version: str = ""


class MetricRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._sources: dict[str, str] = {}

    def register(self, metric: Any, source: str = "builtin") -> None:
        name = getattr(metric, "name", None)
        if not name:
            raise PluginError("Метрика должна иметь атрибут name")
        self._items[name] = metric
        self._sources[name] = source

    def all(self) -> list[Any]:
        return [self._items[name] for name in sorted(self._items)]

    def get(self, name: str) -> Any:
        return self._items.get(name)

    def names(self) -> list[str]:
        return sorted(self._items)

    def sources(self) -> dict[str, str]:
        return dict(self._sources)


class RuleRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._sources: dict[str, str] = {}

    def register(self, rule: Any, source: str = "builtin") -> None:
        name = getattr(rule, "name", None)
        if not name:
            raise PluginError("Правило должно иметь атрибут name")
        self._items[name] = rule
        self._sources[name] = source

    def all(self) -> list[Any]:
        return [self._items[name] for name in sorted(self._items)]

    def get(self, name: str) -> Any:
        return self._items.get(name)

    def names(self) -> list[str]:
        return sorted(self._items)

    def sources(self) -> dict[str, str]:
        return dict(self._sources)


def _iter_entry_points(group: str) -> Iterable[importlib.metadata.EntryPoint]:
    try:
        eps = importlib.metadata.entry_points()
        if hasattr(eps, "select"):
            return list(eps.select(group=group))
        return list(eps.get(group, []))  # pragma: no cover - старый Python
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось прочитать entry points %s: %s", group, exc)
        return []


@dataclass
class LoadedPlugin:
    module: str
    source: str
    info: list[PluginInfo]


class PluginManager:
    """Загружает метрики и правила из entry points и каталогов плагинов."""

    def __init__(
        self,
        metric_registry: MetricRegistry,
        rule_registry: RuleRegistry,
        container: ServiceContainer,
        extra_dirs: Iterable[Path] = (),
    ) -> None:
        self.metrics = metric_registry
        self.rules = rule_registry
        self.container = container
        self.dirs = [Path(d) for d in extra_dirs]
        self.loaded: list[LoadedPlugin] = []

    def load_all(self) -> list[LoadedPlugin]:
        self._load_entry_points()
        seen: set[Path] = set()
        for directory in self.dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                self._load_file(path)
        return list(self.loaded)

    def _load_entry_points(self) -> None:
        for group, registry, kind in (
            (METRIC_ENTRY_POINT, self.metrics, "metric"),
            (RULE_ENTRY_POINT, self.rules, "rule"),
        ):
            for ep in _iter_entry_points(group):
                try:
                    target = ep.load()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Плагин %s не загружен: %s", ep.name, exc)
                    continue
                self._register_target(target, registry, kind, source=f"entrypoint:{ep.name}")
                self.loaded.append(
                    LoadedPlugin(
                        module=ep.value,
                        source=f"entrypoint:{ep.name}",
                        info=[PluginInfo(kind=kind, name=ep.name, source=f"entrypoint:{ep.name}")],
                    )
                )

    @staticmethod
    def _register_target(target: Any, registry: Any, kind: str, source: str) -> None:
        candidates: list[Any]
        if isinstance(target, type):
            candidates = [target]
        elif isinstance(target, (list, tuple, set)):
            candidates = list(target)
        elif hasattr(target, "__iter__") and not isinstance(target, (str, bytes)):
            candidates = list(target)
        else:
            candidates = [target]
        for item in candidates:
            try:
                instance = item() if isinstance(item, type) else item
                registry.register(instance, source=source)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось зарегистрировать %s из %s: %s", item, source, exc)

    def _load_file(self, path: Path) -> None:
        module_name = f"projectpulse_plugin_{path.stem}_{abs(hash(path)) % 100000}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Нет загрузчика для плагина %s", path)
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ошибка выполнения плагина %s: %s", path, exc)
            sys.modules.pop(module_name, None)
            return

        source = f"file:{path}"
        infos: list[PluginInfo] = []
        for metric in getattr(module, "METRICS", []):
            try:
                instance = metric() if isinstance(metric, type) else metric
                self.metrics.register(instance, source=source)
                infos.append(
                    PluginInfo(
                        kind="metric",
                        name=getattr(instance, "name", "?"),
                        source=source,
                        version=getattr(instance, "version", ""),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Метрика плагина %s не загружена: %s", path, exc)
        for rule in getattr(module, "RULES", []):
            try:
                instance = rule() if isinstance(rule, type) else rule
                self.rules.register(instance, source=source)
                infos.append(
                    PluginInfo(
                        kind="rule",
                        name=getattr(instance, "name", "?"),
                        source=source,
                        version=getattr(instance, "version", ""),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Правило плагина %s не загружено: %s", path, exc)

        register = getattr(module, "register", None)
        if callable(register):
            try:
                register(self.container)
                infos.append(PluginInfo(kind="service", name=path.stem, source=source))
            except Exception as exc:  # noqa: BLE001
                logger.warning("register() плагина %s завершился ошибкой: %s", path, exc)

        self.loaded.append(LoadedPlugin(module=str(path), source=source, info=infos))
        logger.info("Загружен плагин %s: %d регистраций", path.name, len(infos))


def load_plugins(metric_registry: MetricRegistry, rule_registry: RuleRegistry, container: ServiceContainer, dirs: Iterable[Path]) -> PluginManager:
    manager = PluginManager(metric_registry, rule_registry, container, dirs)
    manager.load_all()
    return manager
