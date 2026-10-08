-- The event_log table is the durable, authoritative Task Manager journal.
-- These indexes support dashboard/API/MCP filtering without copying events to
-- an in-memory projection.
CREATE INDEX IF NOT EXISTS idx_events_at ON event_log(at DESC);
CREATE INDEX IF NOT EXISTS idx_events_name ON event_log(event, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_provider ON event_log(provider, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_attempt ON event_log(attempt_id, id DESC);
