CREATE TABLE IF NOT EXISTS jev_health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    credential_present INTEGER NOT NULL,
    api_reachable INTEGER NOT NULL DEFAULT 0,
    authentication_ok INTEGER NOT NULL DEFAULT 0,
    model_requested TEXT,
    model_resolved TEXT,
    available_models_json TEXT NOT NULL DEFAULT '[]',
    evaluation_ok INTEGER NOT NULL DEFAULT 0,
    selected_deliver_id TEXT,
    candidate_deliver_ids_json TEXT NOT NULL DEFAULT '[]',
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    error_kind TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_jev_health_checked
ON jev_health_checks(checked_at DESC);
