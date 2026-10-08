-- Explicit Task Manager grants. These add candidates to a task's graph search;
-- Jev still decides whether any candidate enters the model context.
CREATE TABLE task_context_bindings (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    source_key TEXT NOT NULL REFERENCES context_sources(source_key) ON DELETE CASCADE,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(task_id, source_key)
);

CREATE INDEX idx_task_context_bindings_source ON task_context_bindings(source_key, active);
