-- Manual tasks, prompt planner proposals. Additive only.
ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'registry';   -- registry | manual | planner
ALTER TABLE tasks ADD COLUMN title TEXT;
CREATE TABLE plan_proposals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_task_id     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected | invalid
    request          TEXT NOT NULL,                     -- the user's prompt
    proposal         TEXT NOT NULL,                     -- JSON from the planner model
    validation       TEXT NOT NULL DEFAULT '[]',        -- JSON list of {level, message}
    created_task_ids TEXT NOT NULL DEFAULT '[]',
    decided_at       TEXT
);
