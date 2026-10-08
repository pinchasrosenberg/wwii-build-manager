-- Systems brought in through a manifest (wwii-build onboard): one row per generated context file.
CREATE TABLE IF NOT EXISTS system_onboarding (
    system_id          TEXT NOT NULL,
    deliver_id         TEXT NOT NULL,        -- __index__ for the system map file
    manifest_ref       TEXT NOT NULL,
    context_path       TEXT NOT NULL,        -- repo-relative RAG context file
    content_sha256     TEXT NOT NULL,
    graph_status       TEXT,                 -- NULL (not sent) | INGESTED | FAILED
    graph_detail       TEXT,
    graph_ingested_sha TEXT,
    graph_ingested_at  TEXT,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (system_id, deliver_id)
);
