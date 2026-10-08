CREATE TABLE IF NOT EXISTS planner_attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_task_id   TEXT NOT NULL REFERENCES tasks(task_id),
    original_name  TEXT NOT NULL,
    stored_path    TEXT NOT NULL,
    media_type     TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK(kind IN ('image','text','file')),
    size_bytes     INTEGER NOT NULL,
    sha256         TEXT NOT NULL,
    text_excerpt   TEXT,
    selected_at    TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_planner_attachments_task
ON planner_attachments(plan_task_id, id);
