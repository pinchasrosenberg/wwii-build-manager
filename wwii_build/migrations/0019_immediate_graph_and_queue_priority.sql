ALTER TABLE tasks ADD COLUMN dispatch_priority INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_tasks_ready_priority
ON tasks(state, dispatch_priority DESC, wave, task_id);

ALTER TABLE graph_console_queries ADD COLUMN provider TEXT;
ALTER TABLE graph_console_queries ADD COLUMN input_tokens INTEGER;
ALTER TABLE graph_console_queries ADD COLUMN cached_input_tokens INTEGER;
ALTER TABLE graph_console_queries ADD COLUMN output_tokens INTEGER;
ALTER TABLE graph_console_queries ADD COLUMN reported_cost_usd REAL;
