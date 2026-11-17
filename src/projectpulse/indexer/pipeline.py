"""Инкрементальная индексация репозитория и полный цикл анализа."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from projectpulse.analysis.api import interface_volatility
from projectpulse.analysis.context import MetricSet, RepoContext
from projectpulse.analysis.graph import (
    DependencyGraph,
    build_entity_graph,
    build_file_graph,
)
from projectpulse.analysis.health import compute_health
from projectpulse.analysis.metrics.builtin import compute_metrics, default_metrics
from projectpulse.analysis.parser import ParsedFile, analyze_bytes
from projectpulse.analysis.rules.builtin import default_rules
from projectpulse.analysis.rules.engine import evaluate_rules
from projectpulse.core.config import AppConfig
from projectpulse.core.events import (
    CancelToken,
    GitError,
    IndexCancelled,
    NullProgress,
    Progress,
    RepoError,
)
from projectpulse.core.utils import format_duration_ms, iso
from projectpulse.gitio.runner import GitRunner, is_python_path
from projectpulse.storage.db import Store

logger = logging.getLogger("projectpulse.indexer")


@dataclass
class IndexResult:
    repo_id: int
    run_id: int
    kind: str
    duration_ms: int
    commits_seen: int
    commits_new: int
    files_parsed: int
    files_skipped: int
    snapshots: int
    health_score: float
    findings: int
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.kind}: {self.commits_new} новых коммитов, {self.files_parsed} файлов, "
            f"{self.findings} рисков, здоровье {self.health_score:.1f}/100, "
            f"{format_duration_ms(self.duration_ms)}"
        )


class Indexer:
    def __init__(
        self,
        store: Store,
        config: AppConfig,
        git: GitRunner | None = None,
        metrics=None,
        rules=None,
    ) -> None:
        self.store = store
        self.config = config
        self.git = git or GitRunner(timeout=config.git_timeout)
        self.metrics = list(metrics) if metrics is not None else default_metrics()
        self.rules = list(rules) if rules is not None else default_rules()

    # ------------------------------------------------------------------ repos
    def add_repository(self, path: str | Path, name: str | None = None, url: str | None = None) -> dict:
        repo_path = self.git.ensure_repository(path)
        head = self.git.head_sha(repo_path)
        branch = self.git.current_branch(repo_path)
        repo = self.store.add_repo(name or repo_path.name, str(repo_path), url or self.git.remote_url(repo_path))
        if repo and not repo.get("head_sha") and head:
            self.store.update_repo_state(int(repo["id"]), head_sha=head, branch=branch)
            repo = self.store.get_repo(int(repo["id"]))
        return repo  # type: ignore[return-value]

    # ------------------------------------------------------------------ entry
    def index(
        self,
        repo_id: int,
        mode: str = "incremental",
        progress=None,
        cancel: CancelToken | None = None,
    ) -> IndexResult:
        if mode not in {"full", "incremental", "rebuild"}:
            raise ValueError(f"Неизвестный режим индексации: {mode}")
        progress = progress or NullProgress()
        cancel = cancel or CancelToken()
        repo = self.store.get_repo(repo_id)
        if not repo:
            raise RepoError(f"Репозиторий {repo_id} не добавлен")
        repo_path = Path(repo["path"])
        started = time.perf_counter()
        warnings: list[str] = []
        stats: dict = {"warnings": warnings}

        try:
            self.git.ensure_repository(repo_path)
            head = self.git.head_sha(repo_path)
            if not head:
                raise RepoError("В репозитории нет коммитов (unborn HEAD)")
            branch = self.git.current_branch(repo_path)
            old_head = repo.get("head_sha")

            need_full = mode in {"full", "rebuild"}
            kind = "full" if mode == "full" else ("rebuild" if mode == "rebuild" else "incremental")
            if mode == "incremental":
                if not old_head:
                    need_full = True
                    kind = "full"
                    warnings.append("Первичный импорт: истории ещё нет")
                else:
                    try:
                        if not self.git.is_ancestor(repo_path, old_head, head):
                            need_full = True
                            kind = "full"
                            warnings.append("Старый HEAD не является предком нового: выполнен полный импорт")
                            stats["fallback"] = "diverged_history"
                    except GitError:
                        need_full = True
                        kind = "full"
                        warnings.append("Не удалось проверить родство коммитов: выполнен полный импорт")
                        stats["fallback"] = "unknown_history"

            if need_full:
                self.store.clear_repo_data(repo_id)
                cancel.check()
                run_id = self.store.start_run(repo_id, kind, head)
                try:
                    result = self._full(
                        repo, repo_path, head, branch, run_id, progress, cancel, stats, warnings, kind=kind
                    )
                except IndexCancelled:
                    self.store.finish_run(
                        run_id,
                        status="cancelled",
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        head_sha=head,
                        error="Отменено пользователем",
                        stats=stats,
                    )
                    raise
                except Exception as exc:
                    self.store.finish_run(
                        run_id,
                        status="failed",
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        head_sha=head,
                        error=str(exc),
                        stats=stats,
                    )
                    logger.exception("Полная индексация %s завершилась ошибкой", repo["name"])
                    raise
            else:
                assert old_head is not None
                cancel.check()
                run_id = self.store.start_run(repo_id, kind, head)
                try:
                    result = self._incremental(
                        repo, repo_path, old_head, head, branch, run_id, progress, cancel, stats, warnings
                    )
                except IndexCancelled:
                    self.store.finish_run(
                        run_id,
                        status="cancelled",
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        head_sha=head,
                        error="Отменено пользователем",
                        stats=stats,
                    )
                    raise
                except Exception as exc:
                    self.store.finish_run(
                        run_id,
                        status="failed",
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        head_sha=head,
                        error=str(exc),
                        stats=stats,
                    )
                    logger.exception("Инкрементальная индексация %s завершилась ошибкой", repo["name"])
                    raise

            duration_ms = int((time.perf_counter() - started) * 1000)
            result.duration_ms = duration_ms
            self.store.finish_run(
                run_id,
                status="ok",
                duration_ms=duration_ms,
                head_sha=head,
                commits_seen=result.commits_seen,
                commits_new=result.commits_new,
                files_parsed=result.files_parsed,
                files_skipped=result.files_skipped,
                stats=stats,
            )
            counts = self.store.counts(repo_id)
            update: dict = {
                "head_sha": head,
                "branch": branch,
                "last_indexed_at": iso(),
                "last_run_id": run_id,
                "files_total": counts["files"],
                "commits_total": counts["commits"],
                "authors_total": counts["authors"],
            }
            if kind in {"full", "rebuild"}:
                update["full_index_ms"] = duration_ms
            if kind == "incremental":
                update["incremental_index_ms"] = duration_ms
            self.store.update_repo_state(repo_id, **update)
            logger.info("Индексация %s: %s", repo["name"], result.summary())
            return result
        except IndexCancelled:
            raise
        except Exception as exc:
            if not isinstance(exc, RepoError):
                logger.exception("Индексация %s прервана", repo.get("name"))
            raise

    # ------------------------------------------------------------------- full
    def _full(
        self,
        repo: dict,
        repo_path: Path,
        head: str,
        branch: str,
        run_id: int,
        progress,
        cancel: CancelToken,
        stats: dict,
        warnings: list[str],
        kind: str = "full",
    ) -> IndexResult:
        repo_id = int(repo["id"])
        timings: dict[str, int] = {}
        phase_started = time.perf_counter()

        self._emit(progress, "history", "Чтение истории git", 0, 1)
        cancel.check()
        records = self.git.history(repo_path, bugfix_pattern=self.config.thresholds.bugfix_pattern)
        as_of = max((record.ts for record in records), default=0)
        commit_rows: list[dict] = []
        change_rows: list[dict] = []
        for record in records:
            commit_rows.append(record.as_dict())
            for change in record.changes:
                change_rows.append(
                    {
                        "commit_sha": record.sha,
                        "path": change.path,
                        "additions": change.additions,
                        "deletions": change.deletions,
                        "is_binary": int(change.is_binary),
                    }
                )
        cancel.check()
        self._emit(progress, "commits", f"Запись {len(records)} коммитов", 0, 1)
        self.store.insert_commits(repo_id, commit_rows, change_rows)
        timings["history"] = int((time.perf_counter() - phase_started) * 1000)

        phase_started = time.perf_counter()
        self._emit(progress, "files", "Разбор файлов HEAD", 0, 1)
        cache: dict[tuple[str, str], ParsedFile] = {}
        parsed_map, file_rows, skipped, parse_errors = self._parse_tree(
            repo_path, head, cache, progress, cancel, "files"
        )
        cancel.check()
        self._emit(progress, "storage", "Сохранение сущностей и импортов", 0, 1)
        entities, refs, imports = self._collect_analysis(parsed_map)
        self.store.replace_all_analysis(repo_id, file_rows, entities, refs, imports)
        timings["files"] = int((time.perf_counter() - phase_started) * 1000)

        phase_started = time.perf_counter()
        self._emit(progress, "graph", "Построение графов зависимостей", 0, 1)
        file_graph = build_file_graph(file_rows, imports)
        entity_graph = build_entity_graph(file_rows, entities, refs)
        timings["graph"] = int((time.perf_counter() - phase_started) * 1000)

        phase_started = time.perf_counter()
        history_metrics = self._interface_volatility(
            repo_path, head, parsed_map, change_rows, as_of, progress, cancel
        )
        timings["interface"] = int((time.perf_counter() - phase_started) * 1000)

        phase_started = time.perf_counter()
        self._create_snapshots(
            repo, repo_path, head, branch, parsed_map, file_rows, file_graph, entity_graph,
            cache, progress, cancel, warnings,
        )
        timings["snapshots"] = int((time.perf_counter() - phase_started) * 1000)

        cancel.check()
        metrics, findings, health = self._analyse(
            repo_id, run_id, history_metrics, progress, cancel, timings
        )

        stats.update(
            {
                "phase_ms": timings,
                "parse_errors": parse_errors,
                "files_parsed": len(parsed_map),
                "files_skipped": skipped,
                "history_metrics_files": len(history_metrics),
            }
        )
        return IndexResult(
            repo_id=repo_id,
            run_id=run_id,
            kind=kind,
            duration_ms=0,
            commits_seen=len(records),
            commits_new=len(records),
            files_parsed=len(parsed_map),
            files_skipped=skipped,
            snapshots=len(self.store.list_snapshots(repo_id)),
            health_score=health["score"],
            findings=len(findings),
            warnings=warnings,
        )

    # ------------------------------------------------------------ incremental
    def _incremental(
        self,
        repo: dict,
        repo_path: Path,
        old_head: str,
        head: str,
        branch: str,
        run_id: int,
        progress,
        cancel: CancelToken,
        stats: dict,
        warnings: list[str],
    ) -> IndexResult:
        repo_id = int(repo["id"])
        timings: dict[str, int] = {}
        phase_started = time.perf_counter()
        self._emit(progress, "history", "Чтение новых коммитов", 0, 1)
        cancel.check()
        records = self.git.history(
            repo_path, since=old_head, bugfix_pattern=self.config.thresholds.bugfix_pattern
        )
        commit_rows: list[dict] = []
        change_rows: list[dict] = []
        changed_paths: set[str] = set()
        for record in records:
            commit_rows.append(record.as_dict())
            for change in record.changes:
                change_rows.append(
                    {
                        "commit_sha": record.sha,
                        "path": change.path,
                        "additions": change.additions,
                        "deletions": change.deletions,
                        "is_binary": int(change.is_binary),
                    }
                )
                if is_python_path(change.path):
                    changed_paths.add(change.path)
        if commit_rows:
            self._emit(progress, "commits", f"Запись {len(commit_rows)} новых коммитов", 0, 1)
            self.store.insert_commits(repo_id, commit_rows, change_rows)
        timings["history"] = int((time.perf_counter() - phase_started) * 1000)
        cancel.check()

        phase_started = time.perf_counter()
        files_parsed = 0
        skipped = 0
        parse_errors = 0
        if changed_paths:
            self._emit(progress, "files", f"Обновление {len(changed_paths)} файлов", 0, len(changed_paths))
            tree = {info.path: info for info in self.git.tree_files(repo_path, head) if is_python_path(info.path)}
            existing = [path for path in sorted(changed_paths) if path in tree]
            removed = [path for path in sorted(changed_paths) if path not in tree]
            if removed:
                self.store.delete_files(repo_id, removed)
            cache: dict[tuple[str, str], ParsedFile] = {}
            for index, path in enumerate(existing, start=1):
                cancel.check()
                info = tree[path]
                parsed = self._parse_one(repo_path, path, info.sha, cache)
                if parsed is None:
                    skipped += 1
                    self.store.delete_files(repo_id, [path])
                else:
                    file_row = parsed.file_row()
                    self.store.replace_file_analysis(
                        repo_id,
                        path,
                        file_row,
                        [entity.as_dict() for entity in parsed.entities],
                        [ref.as_dict() for ref in parsed.refs],
                        [imp.as_dict() for imp in parsed.imports],
                    )
                    files_parsed += 1
                    if parsed.parse_error:
                        parse_errors += 1
                self._emit(progress, "files", f"Обновлён {path}", index, len(existing))
        timings["files"] = int((time.perf_counter() - phase_started) * 1000)
        cancel.check()

        phase_started = time.perf_counter()
        self._emit(progress, "graph", "Перестроение графа", 0, 1)
        files = self.store.get_files(repo_id)
        entities = self.store.get_entities(repo_id)
        refs = self.store.get_entity_refs(repo_id)
        imports = self.store.get_file_imports(repo_id)
        file_graph = build_file_graph(files, imports)
        entity_graph = build_entity_graph(files, entities, refs)
        as_of = max((int(commit["ts"]) for commit in self.store.get_commits(repo_id)), default=0)
        timings["graph"] = int((time.perf_counter() - phase_started) * 1000)

        history_metrics = self._interface_volatility_for_files(
            repo_path,
            files,
            self.store.get_commits(repo_id),
            self.store.get_commit_files(repo_id),
            as_of,
            progress,
            cancel,
        )

        phase_started = time.perf_counter()
        self._snapshot_head_if_needed(
            repo, repo_path, head, branch, progress, cancel, warnings
        )
        timings["snapshots"] = int((time.perf_counter() - phase_started) * 1000)

        cancel.check()
        metrics, findings, health = self._analyse(
            repo_id, run_id, history_metrics, progress, cancel, timings
        )

        stats.update(
            {
                "phase_ms": timings,
                "parse_errors": parse_errors,
                "files_parsed": files_parsed,
                "files_skipped": skipped,
                "changed_paths": len(changed_paths),
                "history_metrics_files": len(history_metrics),
            }
        )
        return IndexResult(
            repo_id=repo_id,
            run_id=run_id,
            kind="incremental",
            duration_ms=0,
            commits_seen=len(records),
            commits_new=len(records),
            files_parsed=files_parsed,
            files_skipped=skipped,
            snapshots=len(self.store.list_snapshots(repo_id)),
            health_score=health["score"],
            findings=len(findings),
            warnings=warnings,
        )

    # --------------------------------------------------------------- analysis
    def _analyse(self, repo_id: int, run_id: int, history_metrics: dict, progress, cancel: CancelToken, timings: dict):
        repo = self.store.get_repo(repo_id)
        cancel.check()
        phase_started = time.perf_counter()
        self._emit(progress, "metrics", "Расчёт метрик", 0, 1)
        files = self.store.get_files(repo_id)
        commits = self.store.get_commits(repo_id)
        commit_files = self.store.get_commit_files(repo_id)
        entities = self.store.get_entities(repo_id)
        refs = self.store.get_entity_refs(repo_id)
        imports = self.store.get_file_imports(repo_id)
        file_graph = build_file_graph(files, imports)
        entity_graph = build_entity_graph(files, entities, refs)
        context = RepoContext(
            repo=repo or {},
            as_of=max((int(commit["ts"]) for commit in commits), default=0),
            files=files,
            commits=commits,
            commit_files=commit_files,
            entities=entities,
            refs=refs,
            imports=imports,
            file_graph=file_graph,
            entity_graph=entity_graph,
            thresholds=self.config.thresholds,
            history_metrics=history_metrics,
        )
        metric_rows = compute_metrics(self.metrics, context, logger)
        self.store.replace_metric_values(run_id, repo_id, metric_rows)
        series_rows: list[dict] = []
        for metric_name, rows in context.series.items():
            for row in rows:
                series_rows.append({"metric": metric_name, "bucket": row["bucket"], "value": row["value"]})
        self.store.replace_series(repo_id, series_rows)
        timings["metrics"] = int((time.perf_counter() - phase_started) * 1000)

        cancel.check()
        phase_started = time.perf_counter()
        self._emit(progress, "rules", "Проверка правил риска", 0, 1)
        metrics = MetricSet(metric_rows)
        findings = evaluate_rules(self.rules, context, metrics, logger)
        self.store.insert_findings(run_id, repo_id, findings)
        health = compute_health(findings, metrics, context)
        self.store.insert_health(
            run_id,
            repo_id,
            health["score"],
            {
                "label": health["label"],
                "penalty": health["penalty"],
                "components": health["components"],
                "counts": health["counts"],
                "summary": health["summary"],
            },
        )
        timings["rules"] = int((time.perf_counter() - phase_started) * 1000)
        self._emit(progress, "done", "Анализ завершён", 1, 1)
        return metric_rows, findings, health

    # ------------------------------------------------------------------ files
    def _parse_one(
        self,
        repo_path: Path,
        path: str,
        blob_sha: str,
        cache: dict[tuple[str, str], ParsedFile],
    ) -> ParsedFile | None:
        key = (path, blob_sha)
        if key in cache:
            return cache[key]
        raw_map = self.git.read_blobs(repo_path, [blob_sha])
        raw = raw_map.get(blob_sha)
        if raw is None:
            return None
        if len(raw) > self.config.max_file_bytes or b"\x00" in raw[:8192]:
            return None
        parsed = analyze_bytes(path, raw, blob_sha=blob_sha)
        cache[key] = parsed
        return parsed

    def _parse_tree(
        self,
        repo_path: Path,
        ref: str,
        cache: dict[tuple[str, str], ParsedFile],
        progress,
        cancel: CancelToken,
        phase: str,
    ) -> tuple[dict[str, ParsedFile], list[dict], int, int]:
        tree = [info for info in self.git.tree_files(repo_path, ref) if is_python_path(info.path)]
        tree.sort(key=lambda info: info.path)
        if len(tree) > self.config.max_snapshot_files:
            tree = tree[: self.config.max_snapshot_files]
        parsed_map: dict[str, ParsedFile] = {}
        skipped = 0
        parse_errors = 0
        batch = 100
        for start in range(0, len(tree), batch):
            cancel.check()
            chunk = tree[start : start + batch]
            blobs = self.git.read_blobs(
                repo_path,
                [info.sha for info in chunk if (info.path, info.sha) not in cache],
            )
            for info in chunk:
                key = (info.path, info.sha)
                parsed = cache.get(key)
                if parsed is None:
                    raw = blobs.get(info.sha)
                    if raw is None or len(raw) > self.config.max_file_bytes or b"\x00" in raw[:8192]:
                        skipped += 1
                        continue
                    parsed = analyze_bytes(info.path, raw, blob_sha=info.sha)
                    cache[key] = parsed
                parsed_map[info.path] = parsed
                if parsed.parse_error:
                    parse_errors += 1
            self._emit(
                progress,
                phase,
                f"Разобрано {min(start + batch, len(tree))} из {len(tree)} файлов",
                min(start + batch, len(tree)),
                len(tree),
            )
        return parsed_map, [parsed.file_row() for parsed in parsed_map.values()], skipped, parse_errors

    @staticmethod
    def _collect_analysis(parsed_map: dict[str, ParsedFile]) -> tuple[list[dict], list[dict], list[dict]]:
        entities: list[dict] = []
        refs: list[dict] = []
        imports: list[dict] = []
        for path in sorted(parsed_map):
            parsed = parsed_map[path]
            entities.extend(entity.as_dict() for entity in parsed.entities)
            refs.extend(ref.as_dict() for ref in parsed.refs)
            imports.extend(imp.as_dict() for imp in parsed.imports)
        return entities, refs, imports

    # ------------------------------------------------------------ volatility
    def _interface_volatility(
        self,
        repo_path: Path,
        head: str,
        parsed_map: dict[str, ParsedFile],
        change_rows: Sequence[dict],
        as_of: int,
        progress,
        cancel: CancelToken,
    ) -> dict:
        counts: Counter[str] = Counter()
        for change in change_rows:
            if change["path"] in parsed_map:
                counts[change["path"]] += 1
        paths = [path for path, _count in counts.most_common(self.config.ivi_files_limit)]
        return self._compute_interface_volatility(
            repo_path, paths, as_of, progress, cancel
        )

    def _interface_volatility_for_files(
        self,
        repo_path: Path,
        files: Sequence[dict],
        commits: Sequence[dict],
        commit_files: Sequence[dict],
        as_of: int,
        progress,
        cancel: CancelToken,
    ) -> dict:
        counts: Counter[str] = Counter()
        existing = {row["path"] for row in files}
        for change in commit_files:
            if change["path"] in existing:
                counts[change["path"]] += 1
        paths = [path for path, _count in counts.most_common(self.config.ivi_files_limit)]
        return self._compute_interface_volatility(repo_path, paths, as_of, progress, cancel)

    def _compute_interface_volatility(
        self,
        repo_path: Path,
        paths: Sequence[str],
        as_of: int,
        progress,
        cancel: CancelToken,
    ) -> dict:
        result: dict[str, dict] = {}
        for index, path in enumerate(paths, start=1):
            cancel.check()
            try:
                text = self.git.patch_history(repo_path, path, limit=self.config.ivi_commits_limit)
            except GitError as exc:
                logger.warning("Не удалось прочитать историю %s: %s", path, exc)
                continue
            result[path] = interface_volatility(text, as_of=as_of)
            self._emit(
                progress,
                "interface",
                f"Анализ API: {index} из {len(paths)}",
                index,
                len(paths),
            )
        return result

    # -------------------------------------------------------------- snapshots
    def _create_snapshots(
        self,
        repo: dict,
        repo_path: Path,
        head: str,
        branch: str,
        parsed_map: dict[str, ParsedFile],
        file_rows: Sequence[dict],
        file_graph: DependencyGraph,
        entity_graph: DependencyGraph,
        cache: dict[tuple[str, str], ParsedFile],
        progress,
        cancel: CancelToken,
        warnings: list[str],
    ) -> None:
        repo_id = int(repo["id"])
        entries: list[tuple[str, str, str, int]] = []
        entries.append((f"HEAD ({branch or 'detached'})", "HEAD", head, 0))
        for tag in self.git.tags(repo_path, limit=self.config.max_snapshot_tags):
            entries.append((tag.name, f"tag:{tag.name}", tag.sha, tag.ts))
        for ref in self.git.branches(repo_path, limit=self.config.max_snapshot_branches):
            if ref.sha == head:
                continue
            entries.append((ref.name, f"branch:{ref.name}", ref.sha, ref.ts))

        deduped: dict[str, dict] = {}
        order: list[str] = []
        for label, ref_name, sha, ts in entries:
            if sha not in deduped:
                deduped[sha] = {"labels": [label], "refs": [ref_name], "ts": ts}
                order.append(sha)
            else:
                deduped[sha]["labels"].append(label)
                deduped[sha]["refs"].append(ref_name)
                deduped[sha]["ts"] = max(deduped[sha]["ts"], ts)

        # HEAD ставим последним, остальные срезы - по времени создания.
        order.sort(key=lambda sha: (sha == head, deduped[sha]["ts"], deduped[sha]["labels"][0]))
        total = len(order)
        for index, sha in enumerate(order, start=1):
            cancel.check()
            info = deduped[sha]
            label = ", ".join(dict.fromkeys(info["labels"]))
            ref_name = info["refs"][0]
            if sha == head:
                nodes, edges, cycles, loc_total, metrics = self._snapshot_payload(
                    file_rows, parsed_map, file_graph, entity_graph
                )
            else:
                try:
                    snap_parsed, snap_files, skipped, errors = self._parse_tree(
                        repo_path, sha, cache, progress, cancel, "snapshots"
                    )
                except GitError as exc:
                    warnings.append(f"Срез {label} пропущен: {exc}")
                    continue
                snap_entities, snap_refs, snap_imports = self._collect_analysis(snap_parsed)
                snap_file_graph = build_file_graph(snap_files, snap_imports)
                snap_entity_graph = build_entity_graph(snap_files, snap_entities, snap_refs)
                nodes, edges, cycles, loc_total, metrics = self._snapshot_payload(
                    snap_files, snap_parsed, snap_file_graph, snap_entity_graph
                )
                metrics["parse_errors"] = errors
                metrics["files_skipped"] = skipped
            self.store.create_snapshot(
                repo_id,
                label=label,
                ref=ref_name,
                commit_sha=sha,
                nodes=nodes,
                edges=edges,
                cycles_count=cycles,
                loc_total=loc_total,
                metrics=metrics,
            )
            self._emit(progress, "snapshots", f"Срез {index} из {total}: {label}", index, total)
        logger.info("Создано срезов графа: %s", len(order))

    def _snapshot_head_if_needed(
        self,
        repo: dict,
        repo_path: Path,
        head: str,
        branch: str,
        progress,
        cancel: CancelToken,
        warnings: list[str],
    ) -> None:
        repo_id = int(repo["id"])
        latest = self.store.latest_snapshot(repo_id, ref="HEAD")
        if latest and latest.get("commit_sha") == head:
            return
        existing_refs = {row.get("ref") for row in self.store.list_snapshots(repo_id)}
        self._emit(progress, "snapshots", "Обновление среза HEAD", 0, 1)
        cache: dict[tuple[str, str], ParsedFile] = {}
        parsed_map, file_rows, _skipped, errors = self._parse_tree(
            repo_path, head, cache, progress, cancel, "snapshots"
        )
        if not parsed_map:
            return
        entities, refs, imports = self._collect_analysis(parsed_map)
        file_graph = build_file_graph(file_rows, imports)
        entity_graph = build_entity_graph(file_rows, entities, refs)
        nodes, edges, cycles, loc_total, metrics = self._snapshot_payload(
            file_rows, parsed_map, file_graph, entity_graph
        )
        metrics["parse_errors"] = errors
        self.store.create_snapshot(
            repo_id,
            label=f"HEAD ({branch or 'detached'})",
            ref="HEAD",
            commit_sha=head,
            nodes=nodes,
            edges=edges,
            cycles_count=cycles,
            loc_total=loc_total,
            metrics=metrics,
        )
        self._emit(progress, "snapshots", "Срез HEAD обновлён", 1, 1)

        # Новые теги, появившиеся после полного импорта, добавляем точечно.
        for tag in self.git.tags(repo_path, limit=self.config.max_snapshot_tags):
            if f"tag:{tag.name}" in existing_refs:
                continue
            cancel.check()
            tag_cache: dict[tuple[str, str], ParsedFile] = {}
            try:
                tag_parsed, tag_files, _skip, tag_errors = self._parse_tree(
                    repo_path, tag.sha, tag_cache, progress, cancel, "snapshots"
                )
            except GitError as exc:
                warnings.append(f"Тег {tag.name} пропущен: {exc}")
                continue
            if not tag_parsed:
                continue
            tag_entities, tag_refs, tag_imports = self._collect_analysis(tag_parsed)
            tag_file_graph = build_file_graph(tag_files, tag_imports)
            tag_entity_graph = build_entity_graph(tag_files, tag_entities, tag_refs)
            nodes, edges, cycles, loc_total, metrics = self._snapshot_payload(
                tag_files, tag_parsed, tag_file_graph, tag_entity_graph
            )
            metrics["parse_errors"] = tag_errors
            self.store.create_snapshot(
                repo_id,
                label=tag.name,
                ref=f"tag:{tag.name}",
                commit_sha=tag.sha,
                nodes=nodes,
                edges=edges,
                cycles_count=cycles,
                loc_total=loc_total,
                metrics=metrics,
            )

    @staticmethod
    def _snapshot_payload(
        file_rows: Sequence[dict],
        parsed_map: dict[str, ParsedFile],
        file_graph: DependencyGraph,
        entity_graph: DependencyGraph,
    ) -> tuple[list[dict], list[dict], int, int, dict]:
        nodes: list[dict] = []
        for node in file_graph.nodes.values():
            nodes.append(node.as_dict())
        for node in entity_graph.nodes.values():
            nodes.append(node.as_dict())
        edges: list[dict] = []
        for edge in file_graph.edges:
            edges.append({"src": edge.src, "dst": edge.dst, "kind": edge.kind, "weight": edge.weight})
        for edge in entity_graph.edges:
            edges.append({"src": edge.src, "dst": edge.dst, "kind": edge.kind, "weight": edge.weight})
        loc_total = sum(int(row.get("loc", 0)) for row in file_rows)
        metrics = {
            "files": len(parsed_map),
            "entities": sum(len(parsed.entities) for parsed in parsed_map.values()),
            "file_edges": file_graph.edge_count(),
            "entity_edges": entity_graph.edge_count(),
            "file_cycles": len(file_graph.cycles()),
            "entity_cycles": len(entity_graph.cycles()),
        }
        return nodes, edges, len(file_graph.cycles()), loc_total, metrics

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _emit(progress, phase: str, message: str, current: int = 0, total: int = 0) -> None:
        try:
            progress(Progress(phase=phase, message=message, current=current, total=total))
        except Exception:  # noqa: BLE001 - UI не должен ломать индексацию
            logger.debug("Ошибка обработчика прогресса", exc_info=True)
