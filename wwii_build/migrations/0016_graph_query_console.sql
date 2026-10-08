CREATE TABLE IF NOT EXISTS graph_console_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('cypher','natural')),
    query_text TEXT NOT NULL,
    model_key TEXT,
    task_id TEXT,
    status TEXT NOT NULL,
    generated_cypher TEXT,
    result_json TEXT,
    elapsed_ms INTEGER,
    error TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_console_queries_created
ON graph_console_queries(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_graph_console_queries_task
ON graph_console_queries(task_id);
