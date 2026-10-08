CREATE TABLE IF NOT EXISTS subtask_patterns (
    pattern_hash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    reuse_count INTEGER NOT NULL DEFAULT 0,
    promotion_threshold INTEGER NOT NULL DEFAULT 3,
    promotion_status TEXT NOT NULL DEFAULT 'learning'
        CHECK(promotion_status IN ('learning','eligible','promoted','rejected')),
    promoted_deliver_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY(promoted_deliver_id) REFERENCES deliver_catalog(deliver_id)
);

CREATE TABLE IF NOT EXISTS subtask_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_hash TEXT NOT NULL,
    parent_task_id TEXT NOT NULL,
    child_task_id TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(pattern_hash, parent_task_id, child_task_id),
    FOREIGN KEY(pattern_hash) REFERENCES subtask_patterns(pattern_hash),
    FOREIGN KEY(parent_task_id) REFERENCES tasks(task_id),
    FOREIGN KEY(child_task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_subtask_occurrences_parent
ON subtask_occurrences(parent_task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS deliver_templates (
    deliver_id TEXT PRIMARY KEY,
    pattern_hash TEXT NOT NULL,
    instructions TEXT NOT NULL,
    model_key TEXT,
    context_files_json TEXT NOT NULL DEFAULT '[]',
    mcp_servers_json TEXT NOT NULL DEFAULT '[]',
    tool_names_json TEXT NOT NULL DEFAULT '[]',
    write_scope_json TEXT NOT NULL DEFAULT '[]',
    acceptance_commands_json TEXT NOT NULL DEFAULT '[]',
    promotion_evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(deliver_id) REFERENCES deliver_catalog(deliver_id),
    FOREIGN KEY(pattern_hash) REFERENCES subtask_patterns(pattern_hash)
);
