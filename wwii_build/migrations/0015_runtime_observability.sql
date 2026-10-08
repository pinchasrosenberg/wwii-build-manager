-- Lightweight persisted execution history for deterministic Delivers.  Their
-- definitions continue to live in deliver_catalog; this table only records
-- actual invocations and intentionally has none of the LLM-attempt machinery.
CREATE TABLE deterministic_deliver_runs (
    run_id TEXT PRIMARY KEY,
    deliver_id TEXT NOT NULL REFERENCES deliver_catalog(deliver_id),
    episode_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','FAILED','CANCELLED')),
    input_bytes INTEGER NOT NULL DEFAULT 0 CHECK(input_bytes >= 0),
    output_bytes INTEGER NOT NULL DEFAULT 0 CHECK(output_bytes >= 0),
    cost_usd REAL NOT NULL DEFAULT 0 CHECK(cost_usd = 0),
    detail_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX idx_deterministic_runs_deliver
ON deterministic_deliver_runs(deliver_id, started_at DESC);

CREATE INDEX idx_deterministic_runs_status
ON deterministic_deliver_runs(status, started_at DESC);

CREATE INDEX idx_context_packs_task_created
ON context_packs(task_id, created_at DESC);

CREATE INDEX idx_context_sources_active_deliver
ON context_sources(active, deliver_id, updated_at DESC);
