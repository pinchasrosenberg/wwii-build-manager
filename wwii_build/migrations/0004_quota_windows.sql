-- Per-window usage (only when a CLI reports it) and data freshness.
ALTER TABLE provider_state ADD COLUMN session_used_percent REAL;
ALTER TABLE provider_state ADD COLUMN weekly_used_percent REAL;
ALTER TABLE provider_state ADD COLUMN data_at TEXT;
