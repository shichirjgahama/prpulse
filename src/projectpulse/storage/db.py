"""Слой хранения: SQLite, схема вручную, потокобезопасные соединения."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from projectpulse.core.utils import iso, utc_now


class Database:
    """Одна БД, отдельное соединение на поток (WAL, foreign keys)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.Lock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @property
    def conn(self) -> sqlite3.Connection:
        connection = getattr(self._local, "conn", None)
        if connection is None:
            connection = self._connect()
            self._local.conn = connection
        return connection

    def initialize(self) -> None:
        with self._schema_lock:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            self.conn.executescript(schema)
            self.conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')"
            )
            self.conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        connection = self.conn
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.tx() as connection:
            connection.executemany(sql, rows)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return default
        return row[0]

    def close(self) -> None:
        connection = getattr(self._local, "conn", None)
        if connection is not None:
            connection.close()
            self._local.conn = None


class Store:
    """Все SQL-запросы приложения собраны здесь."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ repos
    def add_repo(self, name: str, path: str, url: str | None = None) -> dict[str, Any]:
        existing = self.get_repo(path=path)
        if existing:
            self.db.execute(
                "UPDATE repos SET name = ?, url = COALESCE(?, url) WHERE id = ?",
                (name, url, existing["id"]),
            )
            return self.get_repo(existing["id"])  # type: ignore[return-value]
        cursor = self.db.execute(
            "INSERT INTO repos(name, path, url, created_at) VALUES (?, ?, ?, ?)",
            (name, path, url, iso()),
        )
        return self.get_repo(int(cursor.lastrowid))  # type: ignore[return-value]

    def get_repo(self, repo_id: int | None = None, path: str | None = None) -> dict[str, Any] | None:
        if repo_id is not None:
            return self.db.query_one("SELECT * FROM repos WHERE id = ?", (repo_id,))
        if path is not None:
            return self.db.query_one("SELECT * FROM repos WHERE path = ?", (path,))
        return None

    def list_repos(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM repos ORDER BY name COLLATE NOCASE")

    def delete_repo(self, repo_id: int) -> None:
        self.db.execute("DELETE FROM repos WHERE id = ?", (repo_id,))

    def clear_repo_data(self, repo_id: int) -> None:
        with self.db.tx() as connection:
            for table in (
                "health",
                "findings",
                "metric_values",
                "series",
                "graph_snapshots",
                "entity_refs",
                "file_imports",
                "entities",
                "files",
                "commit_files",
                "commits",
                "runs",
            ):
                connection.execute(f"DELETE FROM {table} WHERE repo_id = ?", (repo_id,))
            connection.execute(
                """UPDATE repos SET head_sha = NULL, last_indexed_at = NULL, last_run_id = NULL,
                   files_total = 0, commits_total = 0, authors_total = 0,
                   full_index_ms = NULL, incremental_index_ms = NULL WHERE id = ?""",
                (repo_id,),
            )

    def update_repo_state(
        self,
        repo_id: int,
        *,
        head_sha: str | None = None,
        branch: str | None = None,
        last_indexed_at: str | None = None,
        last_run_id: int | None = None,
        files_total: int | None = None,
        commits_total: int | None = None,
        authors_total: int | None = None,
        full_index_ms: int | None = None,
        incremental_index_ms: int | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("head_sha", head_sha),
            ("branch", branch),
            ("last_indexed_at", last_indexed_at),
            ("last_run_id", last_run_id),
            ("files_total", files_total),
            ("commits_total", commits_total),
            ("authors_total", authors_total),
            ("full_index_ms", full_index_ms),
            ("incremental_index_ms", incremental_index_ms),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                params.append(value)
        if not fields:
            return
        params.append(repo_id)
        self.db.execute(f"UPDATE repos SET {', '.join(fields)} WHERE id = ?", params)

    # ------------------------------------------------------------------- runs
    def start_run(self, repo_id: int, kind: str, head_sha: str | None) -> int:
        cursor = self.db.execute(
            "INSERT INTO runs(repo_id, kind, status, started_at, head_sha) VALUES (?, ?, 'running', ?, ?)",
            (repo_id, kind, iso(), head_sha),
        )
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str = "ok",
        duration_ms: int,
        head_sha: str | None,
        commits_seen: int = 0,
        commits_new: int = 0,
        files_parsed: int = 0,
        files_skipped: int = 0,
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """UPDATE runs SET status = ?, finished_at = ?, duration_ms = ?, head_sha = ?,
               commits_seen = ?, commits_new = ?, files_parsed = ?, files_skipped = ?,
               error = ?, stats_json = ? WHERE id = ?""",
            (
                status,
                iso(),
                duration_ms,
                head_sha,
                commits_seen,
                commits_new,
                files_parsed,
                files_skipped,
                error,
                json.dumps(stats or {}, ensure_ascii=False, sort_keys=True),
                run_id,
            ),
        )

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))

    def list_runs(self, repo_id: int, limit: int = 20) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM runs WHERE repo_id = ? ORDER BY id DESC LIMIT ?", (repo_id, limit)
        )

    def latest_run(self, repo_id: int, status: str | None = "ok") -> dict[str, Any] | None:
        if status:
            return self.db.query_one(
                "SELECT * FROM runs WHERE repo_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
                (repo_id, status),
            )
        return self.db.query_one(
            "SELECT * FROM runs WHERE repo_id = ? ORDER BY id DESC LIMIT 1", (repo_id,)
        )

    # ---------------------------------------------------------------- commits
    def insert_commits(self, repo_id: int, commits: Sequence[dict[str, Any]], changes: Sequence[dict[str, Any]]) -> None:
        with self.db.tx() as connection:
            connection.executemany(
                """INSERT OR REPLACE INTO commits(
                    repo_id, sha, author_name, author_email, ts, message, is_bugfix,
                    insertions, deletions, files_changed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        c["sha"],
                        c.get("author_name", ""),
                        c.get("author_email", ""),
                        int(c["ts"]),
                        c.get("message", ""),
                        int(c.get("is_bugfix", 0)),
                        int(c.get("insertions", 0)),
                        int(c.get("deletions", 0)),
                        int(c.get("files_changed", 0)),
                    )
                    for c in commits
                ],
            )
            connection.executemany(
                """INSERT OR REPLACE INTO commit_files(
                    repo_id, commit_sha, path, additions, deletions, is_binary)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        ch["commit_sha"],
                        ch["path"],
                        int(ch.get("additions", 0)),
                        int(ch.get("deletions", 0)),
                        int(ch.get("is_binary", 0)),
                    )
                    for ch in changes
                ],
            )

    def get_commits(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM commits WHERE repo_id = ? ORDER BY ts, sha", (repo_id,)
        )

    def get_commit_files(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM commit_files WHERE repo_id = ? ORDER BY path, commit_sha", (repo_id,)
        )

    def commit_shas(self, repo_id: int) -> set[str]:
        rows = self.db.query("SELECT sha FROM commits WHERE repo_id = ?", (repo_id,))
        return {str(row["sha"]) for row in rows}

    # ------------------------------------------------------------------ files
    def upsert_files(self, repo_id: int, files: Sequence[dict[str, Any]]) -> None:
        with self.db.tx() as connection:
            connection.executemany(
                """INSERT OR REPLACE INTO files(
                    repo_id, path, blob_sha, language, size_bytes, loc, sloc, comments, blanks,
                    complexity_total, complexity_max, functions, classes, todo_count,
                    parse_error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        f["path"],
                        f.get("blob_sha"),
                        f.get("language", "python"),
                        int(f.get("size_bytes", 0)),
                        int(f.get("loc", 0)),
                        int(f.get("sloc", 0)),
                        int(f.get("comments", 0)),
                        int(f.get("blanks", 0)),
                        int(f.get("complexity_total", 0)),
                        int(f.get("complexity_max", 0)),
                        int(f.get("functions", 0)),
                        int(f.get("classes", 0)),
                        int(f.get("todo_count", 0)),
                        f.get("parse_error"),
                        f.get("updated_at") or iso(),
                    )
                    for f in files
                ],
            )

    def get_files(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM files WHERE repo_id = ? ORDER BY path", (repo_id,))

    def delete_files(self, repo_id: int, paths: Sequence[str]) -> None:
        if not paths:
            return
        placeholders = ",".join("?" for _ in paths)
        with self.db.tx() as connection:
            connection.execute(
                f"DELETE FROM files WHERE repo_id = ? AND path IN ({placeholders})",
                (repo_id, *paths),
            )
            connection.execute(
                f"DELETE FROM entities WHERE repo_id = ? AND path IN ({placeholders})",
                (repo_id, *paths),
            )
            connection.execute(
                f"DELETE FROM entity_refs WHERE repo_id = ? AND path IN ({placeholders})",
                (repo_id, *paths),
            )
            connection.execute(
                f"DELETE FROM file_imports WHERE repo_id = ? AND path IN ({placeholders})",
                (repo_id, *paths),
            )

    def replace_file_analysis(
        self,
        repo_id: int,
        path: str,
        file_row: dict[str, Any],
        entities: Sequence[dict[str, Any]],
        refs: Sequence[dict[str, Any]],
        imports: Sequence[dict[str, Any]],
    ) -> None:
        with self.db.tx() as connection:
            connection.execute(
                "DELETE FROM files WHERE repo_id = ? AND path = ?", (repo_id, path)
            )
            connection.execute(
                "DELETE FROM entities WHERE repo_id = ? AND path = ?", (repo_id, path)
            )
            connection.execute(
                "DELETE FROM entity_refs WHERE repo_id = ? AND path = ?", (repo_id, path)
            )
            connection.execute(
                "DELETE FROM file_imports WHERE repo_id = ? AND path = ?", (repo_id, path)
            )
            connection.execute(
                """INSERT INTO files(repo_id, path, blob_sha, language, size_bytes, loc, sloc,
                   comments, blanks, complexity_total, complexity_max, functions, classes,
                   todo_count, parse_error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    repo_id,
                    path,
                    file_row.get("blob_sha"),
                    file_row.get("language", "python"),
                    int(file_row.get("size_bytes", 0)),
                    int(file_row.get("loc", 0)),
                    int(file_row.get("sloc", 0)),
                    int(file_row.get("comments", 0)),
                    int(file_row.get("blanks", 0)),
                    int(file_row.get("complexity_total", 0)),
                    int(file_row.get("complexity_max", 0)),
                    int(file_row.get("functions", 0)),
                    int(file_row.get("classes", 0)),
                    int(file_row.get("todo_count", 0)),
                    file_row.get("parse_error"),
                    file_row.get("updated_at") or iso(),
                ),
            )
            connection.executemany(
                """INSERT INTO entities(repo_id, entity_id, kind, name, qualname, path,
                   lineno, end_lineno, complexity, is_public, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        e["entity_id"],
                        e["kind"],
                        e["name"],
                        e["qualname"],
                        e["path"],
                        int(e.get("lineno", 0)),
                        int(e.get("end_lineno", 0)),
                        int(e.get("complexity", 0)),
                        int(e.get("is_public", 0)),
                        e.get("parent_id"),
                    )
                    for e in entities
                ],
            )
            connection.executemany(
                """INSERT INTO entity_refs(repo_id, src_id, kind, target, lineno, path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        r["src_id"],
                        r["kind"],
                        r["target"],
                        int(r.get("lineno", 0)),
                        r["path"],
                    )
                    for r in refs
                ],
            )
            connection.executemany(
                """INSERT INTO file_imports(repo_id, path, module, level, names, lineno)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        imp["path"],
                        imp.get("module"),
                        int(imp.get("level", 0)),
                        imp.get("names"),
                        int(imp.get("lineno", 0)),
                    )
                    for imp in imports
                ],
            )

    def replace_all_analysis(
        self,
        repo_id: int,
        files: Sequence[dict[str, Any]],
        entities: Sequence[dict[str, Any]],
        refs: Sequence[dict[str, Any]],
        imports: Sequence[dict[str, Any]],
    ) -> None:
        with self.db.tx() as connection:
            connection.execute("DELETE FROM files WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM entities WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM entity_refs WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM file_imports WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """INSERT INTO files(repo_id, path, blob_sha, language, size_bytes, loc, sloc,
                   comments, blanks, complexity_total, complexity_max, functions, classes,
                   todo_count, parse_error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        f["path"],
                        f.get("blob_sha"),
                        f.get("language", "python"),
                        int(f.get("size_bytes", 0)),
                        int(f.get("loc", 0)),
                        int(f.get("sloc", 0)),
                        int(f.get("comments", 0)),
                        int(f.get("blanks", 0)),
                        int(f.get("complexity_total", 0)),
                        int(f.get("complexity_max", 0)),
                        int(f.get("functions", 0)),
                        int(f.get("classes", 0)),
                        int(f.get("todo_count", 0)),
                        f.get("parse_error"),
                        f.get("updated_at") or iso(),
                    )
                    for f in files
                ],
            )
            connection.executemany(
                """INSERT INTO entities(repo_id, entity_id, kind, name, qualname, path,
                   lineno, end_lineno, complexity, is_public, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        e["entity_id"],
                        e["kind"],
                        e["name"],
                        e["qualname"],
                        e["path"],
                        int(e.get("lineno", 0)),
                        int(e.get("end_lineno", 0)),
                        int(e.get("complexity", 0)),
                        int(e.get("is_public", 0)),
                        e.get("parent_id"),
                    )
                    for e in entities
                ],
            )
            connection.executemany(
                """INSERT INTO entity_refs(repo_id, src_id, kind, target, lineno, path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (repo_id, r["src_id"], r["kind"], r["target"], int(r.get("lineno", 0)), r["path"])
                    for r in refs
                ],
            )
            connection.executemany(
                """INSERT INTO file_imports(repo_id, path, module, level, names, lineno)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        repo_id,
                        imp["path"],
                        imp.get("module"),
                        int(imp.get("level", 0)),
                        imp.get("names"),
                        int(imp.get("lineno", 0)),
                    )
                    for imp in imports
                ],
            )

    def get_entities(self, repo_id: int, path: str | None = None) -> list[dict[str, Any]]:
        if path:
            return self.db.query(
                "SELECT * FROM entities WHERE repo_id = ? AND path = ? ORDER BY path, qualname",
                (repo_id, path),
            )
        return self.db.query(
            "SELECT * FROM entities WHERE repo_id = ? ORDER BY path, qualname", (repo_id,)
        )

    def get_entity_refs(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM entity_refs WHERE repo_id = ? ORDER BY path, src_id, target",
            (repo_id,),
        )

    def get_file_imports(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM file_imports WHERE repo_id = ? ORDER BY path, lineno", (repo_id,)
        )

    # -------------------------------------------------------------- snapshots
    def create_snapshot(
        self,
        repo_id: int,
        label: str,
        ref: str | None,
        commit_sha: str | None,
        nodes: Sequence[dict[str, Any]],
        edges: Sequence[dict[str, Any]],
        cycles_count: int,
        loc_total: int,
        metrics: dict[str, Any] | None = None,
    ) -> int:
        with self.db.tx() as connection:
            cursor = connection.execute(
                """INSERT INTO graph_snapshots(repo_id, label, ref, commit_sha, created_at,
                   nodes_count, edges_count, cycles_count, loc_total, metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    repo_id,
                    label,
                    ref,
                    commit_sha,
                    iso(),
                    len(nodes),
                    len(edges),
                    cycles_count,
                    loc_total,
                    json.dumps(metrics or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            connection.executemany(
                """INSERT INTO snapshot_nodes(snapshot_id, node_id, kind, path, name, loc, complexity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot_id,
                        n["node_id"],
                        n["kind"],
                        n.get("path"),
                        n.get("name"),
                        int(n.get("loc", 0)),
                        int(n.get("complexity", 0)),
                    )
                    for n in nodes
                ],
            )
            connection.executemany(
                """INSERT INTO snapshot_edges(snapshot_id, src, dst, kind, weight)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot_id,
                        e["src"],
                        e["dst"],
                        e["kind"],
                        int(e.get("weight", 1)),
                    )
                    for e in edges
                ],
            )
            return snapshot_id

    def list_snapshots(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM graph_snapshots WHERE repo_id = ? ORDER BY id", (repo_id,)
        )

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM graph_snapshots WHERE id = ?", (snapshot_id,))

    def latest_snapshot(self, repo_id: int, ref: str | None = None) -> dict[str, Any] | None:
        if ref:
            return self.db.query_one(
                "SELECT * FROM graph_snapshots WHERE repo_id = ? AND ref = ? ORDER BY id DESC LIMIT 1",
                (repo_id, ref),
            )
        return self.db.query_one(
            "SELECT * FROM graph_snapshots WHERE repo_id = ? ORDER BY id DESC LIMIT 1", (repo_id,)
        )

    def get_snapshot_nodes(self, snapshot_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM snapshot_nodes WHERE snapshot_id = ? ORDER BY node_id", (snapshot_id,)
        )

    def get_snapshot_edges(self, snapshot_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM snapshot_edges WHERE snapshot_id = ? ORDER BY src, dst, kind",
            (snapshot_id,),
        )

    def clear_snapshots(self, repo_id: int) -> None:
        self.db.execute("DELETE FROM graph_snapshots WHERE repo_id = ?", (repo_id,))

    # ---------------------------------------------------------------- metrics
    def replace_metric_values(self, run_id: int, repo_id: int, values: Sequence[dict[str, Any]]) -> None:
        with self.db.tx() as connection:
            connection.execute("DELETE FROM metric_values WHERE run_id = ?", (run_id,))
            connection.executemany(
                """INSERT INTO metric_values(run_id, repo_id, scope, target, metric, value, extra_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        repo_id,
                        v["scope"],
                        v["target"],
                        v["metric"],
                        float(v["value"]),
                        json.dumps(v.get("extra", {}), ensure_ascii=False, sort_keys=True),
                    )
                    for v in values
                ],
            )

    def get_metric_values(self, run_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM metric_values WHERE run_id = ? ORDER BY metric, scope, target", (run_id,)
        )

    def metric_map(self, run_id: int) -> dict[tuple[str, str, str], float]:
        rows = self.get_metric_values(run_id)
        return {(row["scope"], row["target"], row["metric"]): float(row["value"]) for row in rows}

    def project_metric(self, run_id: int, metric: str, default: float = 0.0) -> float:
        value = self.db.scalar(
            "SELECT value FROM metric_values WHERE run_id = ? AND scope = 'project' AND metric = ?",
            (run_id, metric),
        )
        return float(value) if value is not None else default

    def replace_series(self, repo_id: int, rows: Sequence[dict[str, Any]]) -> None:
        with self.db.tx() as connection:
            connection.execute("DELETE FROM series WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                "INSERT INTO series(repo_id, metric, bucket, value, extra_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        repo_id,
                        row["metric"],
                        row["bucket"],
                        float(row["value"]),
                        json.dumps(row.get("extra", {}), ensure_ascii=False, sort_keys=True),
                    )
                    for row in rows
                ],
            )

    def get_series(self, repo_id: int) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM series WHERE repo_id = ? ORDER BY metric, bucket", (repo_id,)
        )

    def series_map(self, repo_id: int) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for row in self.get_series(repo_id):
            result.setdefault(row["metric"], []).append(row)
        return result

    # --------------------------------------------------------------- findings
    def insert_findings(self, run_id: int, repo_id: int, findings: Sequence[dict[str, Any]]) -> None:
        with self.db.tx() as connection:
            connection.executemany(
                """INSERT INTO findings(run_id, repo_id, rule, severity, target, title,
                   explanation, recommendation, value_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        repo_id,
                        f["rule"],
                        f["severity"],
                        f["target"],
                        f["title"],
                        f["explanation"],
                        f["recommendation"],
                        json.dumps(f.get("value", {}), ensure_ascii=False, sort_keys=True),
                    )
                    for f in findings
                ],
            )

    def get_findings(self, run_id: int) -> list[dict[str, Any]]:
        order = "CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END"
        return self.db.query(
            f"SELECT * FROM findings WHERE run_id = ? ORDER BY {order}, rule, target", (run_id,)
        )

    # ----------------------------------------------------------------- health
    def insert_health(self, run_id: int, repo_id: int, score: float, components: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO health(run_id, repo_id, score, components_json) VALUES (?, ?, ?, ?)",
            (run_id, repo_id, float(score), json.dumps(components, ensure_ascii=False, sort_keys=True)),
        )

    def get_health(self, run_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM health WHERE run_id = ?", (run_id,))
        if row:
            row["components"] = json.loads(row.pop("components_json") or "{}")
        return row

    def latest_health(self, repo_id: int) -> dict[str, Any] | None:
        run = self.latest_run(repo_id)
        if not run:
            return None
        return self.get_health(int(run["id"]))

    # --------------------------------------------------------------- research
    def save_research(self, healthy_repo: str, problematic_repo: str, hypothesis: str, result: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO research_results(created_at, healthy_repo, problematic_repo, hypothesis, result_json)
               VALUES (?, ?, ?, ?, ?)""",
            (iso(), healthy_repo, problematic_repo, hypothesis, json.dumps(result, ensure_ascii=False, sort_keys=True)),
        )

    # ------------------------------------------------------------------ misc
    def counts(self, repo_id: int) -> dict[str, int]:
        return {
            "commits": int(self.db.scalar("SELECT COUNT(*) FROM commits WHERE repo_id = ?", (repo_id,), 0)),
            "authors": int(
                self.db.scalar(
                    "SELECT COUNT(DISTINCT author_email) FROM commits WHERE repo_id = ?", (repo_id,), 0
                )
            ),
            "files": int(self.db.scalar("SELECT COUNT(*) FROM files WHERE repo_id = ?", (repo_id,), 0)),
            "entities": int(self.db.scalar("SELECT COUNT(*) FROM entities WHERE repo_id = ?", (repo_id,), 0)),
        }

    def stats(self, repo_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT COALESCE(SUM(loc), 0) AS loc, COALESCE(SUM(sloc), 0) AS sloc,
               COALESCE(SUM(complexity_total), 0) AS complexity_total,
               COALESCE(MAX(complexity_max), 0) AS complexity_max,
               COALESCE(SUM(comments), 0) AS comments
               FROM files WHERE repo_id = ?""",
            (repo_id,),
        )
        counts = self.counts(repo_id)
        result = dict(row or {})
        result.update(counts)
        result["first_ts"] = self.db.scalar("SELECT MIN(ts) FROM commits WHERE repo_id = ?", (repo_id,))
        result["last_ts"] = self.db.scalar("SELECT MAX(ts) FROM commits WHERE repo_id = ?", (repo_id,))
        return result
