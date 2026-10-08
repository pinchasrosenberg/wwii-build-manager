-- Apply the priority policy immediately to work that predates migration 0019.
-- The boost is consumed and reset when the scheduler starts the task.
UPDATE tasks
SET dispatch_priority = 1000000 + rowid
WHERE kind = 'plan'
  AND COALESCE(dispatch_priority, 0) = 0
  AND state NOT IN ('PASSED', 'FAILED', 'CANCELLED', 'SKIPPED');

UPDATE tasks
SET dispatch_priority = 500000 + rowid
WHERE source = 'manual'
  AND COALESCE(dispatch_priority, 0) = 0
  AND state NOT IN ('PASSED', 'FAILED', 'CANCELLED', 'SKIPPED')
  AND NOT EXISTS (
      SELECT 1 FROM task_dependencies d WHERE d.task_id = tasks.task_id
  );
