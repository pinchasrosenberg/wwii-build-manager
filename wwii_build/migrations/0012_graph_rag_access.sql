CREATE TABLE IF NOT EXISTS deliver_graph_access (
    deliver_id TEXT PRIMARY KEY,
    access_mode TEXT NOT NULL DEFAULT 'none' CHECK(access_mode IN ('none','limited','full')),
    scope_text TEXT,
    max_chunks INTEGER NOT NULL DEFAULT 6,
    max_chars INTEGER NOT NULL DEFAULT 6000,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(deliver_id) REFERENCES deliver_catalog(deliver_id)
);

CREATE TABLE IF NOT EXISTS graph_rag_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    access_mode TEXT NOT NULL,
    query_sha256 TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_graph_rag_queries_scope
ON graph_rag_queries(scope_id, created_at DESC);
