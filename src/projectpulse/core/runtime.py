"""Сборка приложения: конфигурация, хранилище, плагины и индексатор."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from projectpulse.analysis.metrics.builtin import default_metrics, register_default_metrics
from projectpulse.analysis.rules.builtin import default_rules, register_default_rules
from projectpulse.core.config import AppConfig, packaged_plugins_dir
from projectpulse.core.events import close_logging, setup_logging
from projectpulse.core.plugins import (
    MetricRegistry,
    PluginManager,
    RuleRegistry,
    ServiceContainer,
    load_plugins,
)
from projectpulse.gitio.runner import GitRunner
from projectpulse.indexer.pipeline import Indexer
from projectpulse.storage.db import Database, Store


@dataclass
class Runtime:
    config: AppConfig
    database: Database
    store: Store
    git: GitRunner
    metrics: MetricRegistry
    rules: RuleRegistry
    plugins: PluginManager
    indexer: Indexer
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("projectpulse"))

    def find_repo(self, value: str) -> dict | None:
        """Ищет репозиторий по пути или имени."""
        store = self.store
        candidate = Path(value).expanduser()
        if candidate.exists():
            try:
                resolved = self.git.ensure_repository(candidate)
            except Exception:  # noqa: BLE001 - путь может быть не репозиторием
                resolved = None
            if resolved is not None:
                found = store.get_repo(path=str(resolved))
                if found:
                    return found
        by_name = [repo for repo in store.list_repos() if repo["name"] == value]
        if len(by_name) == 1:
            return by_name[0]
        by_path = store.get_repo(path=str(candidate.resolve())) if candidate.exists() else None
        return by_path

    def ensure_repo(self, value: str, name: str | None = None) -> dict:
        repo = self.find_repo(value)
        if repo:
            return repo
        return self.indexer.add_repository(value, name=name)

    def close(self) -> None:
        """Освобождает соединения с БД и файловые обработчики журнала."""
        self.database.close()
        close_logging()


def build_runtime(home: Path | str | None = None, with_plugins: bool = True) -> Runtime:
    config = AppConfig.load(home)
    logger = setup_logging(config.paths.log_path, config.log_level)
    database = Database(config.paths.db_path)
    store = Store(database)
    git = GitRunner(timeout=config.git_timeout)

    metrics = MetricRegistry()
    rules = RuleRegistry()
    register_default_metrics(metrics)
    register_default_rules(rules)
    container = ServiceContainer()
    container.register("config", config)
    container.register("store", store)
    container.register("git", git)
    container.register("metrics", metrics)
    container.register("rules", rules)
    container.register("logger", logger)

    directories = [config.paths.plugins_dir]
    packaged = packaged_plugins_dir()
    if packaged.exists():
        directories.append(packaged)
    plugins = (
        load_plugins(metrics, rules, container, directories)
        if with_plugins
        else PluginManager(metrics, rules, container, [])
    )
    indexer = Indexer(store, config, git=git, metrics=metrics.all(), rules=rules.all())
    container.register("indexer", indexer)
    container.register("plugins", plugins)
    return Runtime(
        config=config,
        database=database,
        store=store,
        git=git,
        metrics=metrics,
        rules=rules,
        plugins=plugins,
        indexer=indexer,
        logger=logger,
    )


def describe_plugins(runtime: Runtime) -> dict:
    builtin_metrics = {metric.name for metric in default_metrics()}
    builtin_rules = {rule.name for rule in default_rules()}
    metric_sources = runtime.metrics.sources()
    rule_sources = runtime.rules.sources()
    return {
        "metrics": [
            {
                "name": name,
                "source": metric_sources.get(name, "builtin"),
                "builtin": name in builtin_metrics,
            }
            for name in runtime.metrics.names()
        ],
        "rules": [
            {
                "name": name,
                "source": rule_sources.get(name, "builtin"),
                "builtin": name in builtin_rules,
            }
            for name in runtime.rules.names()
        ],
        "loaded": [
            {
                "module": item.module,
                "source": item.source,
                "items": [
                    {"kind": info.kind, "name": info.name, "source": info.source, "version": info.version}
                    for info in item.info
                ],
            }
            for item in runtime.plugins.loaded
        ],
    }
