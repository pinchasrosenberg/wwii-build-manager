-- Repair tasks are first-class rows in `tasks` (kind='repair') linked to a parent.
-- Additive only: every new column has a default, so older code keeps working.
ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'task';          -- task | repair
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN repair_no INTEGER;
ALTER TABLE tasks ADD COLUMN failed_attempt_id INTEGER;
ALTER TABLE tasks ADD COLUMN failure_class TEXT;
ALTER TABLE tasks ADD COLUMN failure_summary TEXT;
ALTER TABLE tasks ADD COLUMN repair_context TEXT;                         -- JSON: failing checks, paths, head
ALTER TABLE tasks ADD COLUMN repairs_count INTEGER NOT NULL DEFAULT 0;   -- on parents
ALTER TABLE tasks ADD COLUMN repair_budget_extra INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN active_repair_id TEXT;
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
ALTER TABLE test_results ADD COLUMN via_task_id TEXT;                     -- repair task that triggered the run
