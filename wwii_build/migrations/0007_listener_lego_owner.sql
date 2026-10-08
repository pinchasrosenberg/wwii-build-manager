ALTER TABLE deliver_listener_edges ADD COLUMN source_lego_id TEXT;

CREATE INDEX IF NOT EXISTS idx_listener_source_lego
ON deliver_listener_edges(source_deliver_id, source_lego_id, enabled);
