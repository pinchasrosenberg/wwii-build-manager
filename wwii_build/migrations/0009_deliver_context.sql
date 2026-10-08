ALTER TABLE context_sources ADD COLUMN deliver_id TEXT REFERENCES deliver_catalog(deliver_id);

UPDATE context_sources
SET deliver_id = task_id
WHERE task_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM deliver_catalog d WHERE d.deliver_id = context_sources.task_id);

CREATE INDEX IF NOT EXISTS idx_context_deliver
ON context_sources(deliver_id, active);
