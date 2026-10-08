-- Opt-in web access for research tasks: per-attempt record of whether web tools were enabled for the run,
-- and the Deliver-template opt-in. Both default to closed (0), so existing rows keep their behavior.
ALTER TABLE task_attempts ADD COLUMN web_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE deliver_templates ADD COLUMN allow_web INTEGER NOT NULL DEFAULT 0;
