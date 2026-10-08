CREATE TABLE IF NOT EXISTS system_repair_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    status TEXT NOT NULL CHECK(status IN ('STAGED','ACTIVATED','FAILED')),
    base_commit TEXT NOT NULL,
    candidate_commit TEXT NOT NULL,
    integration_commit TEXT,
    changed_files_json TEXT NOT NULL DEFAULT '[]',
    release_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_system_repair_release_status
ON system_repair_releases(status, created_at DESC);
