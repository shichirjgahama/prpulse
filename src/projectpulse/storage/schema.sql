-- Схема базы ProjectPulse. SQLite, без внешних расширений.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    url TEXT,
    created_at TEXT NOT NULL,
    head_sha TEXT,
    branch TEXT,
    last_indexed_at TEXT,
    last_run_id INTEGER,
    files_total INTEGER NOT NULL DEFAULT 0,
    commits_total INTEGER NOT NULL DEFAULT 0,
    authors_total INTEGER NOT NULL DEFAULT 0,
    full_index_ms INTEGER,
    incremental_index_ms INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    head_sha TEXT,
    commits_seen INTEGER NOT NULL DEFAULT 0,
    commits_new INTEGER NOT NULL DEFAULT 0,
    files_parsed INTEGER NOT NULL DEFAULT 0,
    files_skipped INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    stats_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_repo ON runs(repo_id, id DESC);

CREATE TABLE IF NOT EXISTS commits (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    author_name TEXT,
    author_email TEXT,
    ts INTEGER NOT NULL,
    message TEXT,
    is_bugfix INTEGER NOT NULL DEFAULT 0,
    insertions INTEGER NOT NULL DEFAULT 0,
    deletions INTEGER NOT NULL DEFAULT 0,
    files_changed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (repo_id, sha)
);
CREATE INDEX IF NOT EXISTS ix_commits_ts ON commits(repo_id, ts);

CREATE TABLE IF NOT EXISTS commit_files (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    path TEXT NOT NULL,
    additions INTEGER NOT NULL DEFAULT 0,
    deletions INTEGER NOT NULL DEFAULT 0,
    is_binary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (repo_id, commit_sha, path)
);
CREATE INDEX IF NOT EXISTS ix_commit_files_path ON commit_files(repo_id, path);

CREATE TABLE IF NOT EXISTS files (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    blob_sha TEXT,
    language TEXT NOT NULL DEFAULT 'python',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    loc INTEGER NOT NULL DEFAULT 0,
    sloc INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    blanks INTEGER NOT NULL DEFAULT 0,
    complexity_total INTEGER NOT NULL DEFAULT 0,
    complexity_max INTEGER NOT NULL DEFAULT 0,
    functions INTEGER NOT NULL DEFAULT 0,
    classes INTEGER NOT NULL DEFAULT 0,
    todo_count INTEGER NOT NULL DEFAULT 0,
    parse_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (repo_id, path)
);

CREATE TABLE IF NOT EXISTS entities (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    path TEXT NOT NULL,
    lineno INTEGER NOT NULL DEFAULT 0,
    end_lineno INTEGER NOT NULL DEFAULT 0,
    complexity INTEGER NOT NULL DEFAULT 0,
    is_public INTEGER NOT NULL DEFAULT 0,
    parent_id TEXT,
    PRIMARY KEY (repo_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_entities_path ON entities(repo_id, path);
CREATE INDEX IF NOT EXISTS ix_entities_name ON entities(repo_id, name);

CREATE TABLE IF NOT EXISTS entity_refs (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    src_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    lineno INTEGER NOT NULL DEFAULT 0,
    path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_entity_refs_path ON entity_refs(repo_id, path);
CREATE INDEX IF NOT EXISTS ix_entity_refs_src ON entity_refs(repo_id, src_id);

CREATE TABLE IF NOT EXISTS file_imports (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    module TEXT,
    level INTEGER NOT NULL DEFAULT 0,
    names TEXT,
    lineno INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_file_imports_path ON file_imports(repo_id, path);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    ref TEXT,
    commit_sha TEXT,
    created_at TEXT NOT NULL,
    nodes_count INTEGER NOT NULL DEFAULT 0,
    edges_count INTEGER NOT NULL DEFAULT 0,
    cycles_count INTEGER NOT NULL DEFAULT 0,
    loc_total INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_snapshots_repo ON graph_snapshots(repo_id, id);

CREATE TABLE IF NOT EXISTS snapshot_nodes (
    snapshot_id INTEGER NOT NULL REFERENCES graph_snapshots(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT,
    name TEXT,
    loc INTEGER NOT NULL DEFAULT 0,
    complexity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, node_id)
);

CREATE TABLE IF NOT EXISTS snapshot_edges (
    snapshot_id INTEGER NOT NULL REFERENCES graph_snapshots(id) ON DELETE CASCADE,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (snapshot_id, src, dst, kind)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_edges ON snapshot_edges(snapshot_id, src);

CREATE TABLE IF NOT EXISTS metric_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    target TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    extra_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_metric_values_run ON metric_values(run_id, metric, scope);

CREATE TABLE IF NOT EXISTS series (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    bucket TEXT NOT NULL,
    value REAL NOT NULL,
    extra_json TEXT,
    PRIMARY KEY (repo_id, metric, bucket)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    target TEXT NOT NULL,
    title TEXT NOT NULL,
    explanation TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    value_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_findings_run ON findings(run_id, severity);

CREATE TABLE IF NOT EXISTS health (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    components_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    healthy_repo TEXT NOT NULL,
    problematic_repo TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    result_json TEXT NOT NULL
);
