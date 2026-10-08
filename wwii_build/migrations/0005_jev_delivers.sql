CREATE TABLE IF NOT EXISTS deliver_catalog (
    deliver_id TEXT PRIMARY KEY,
    packet TEXT,
    owner TEXT,
    domain TEXT,
    description TEXT,
    source_kind TEXT NOT NULL DEFAULT 'task_graph',
    source_ref TEXT,
    execution_kind TEXT NOT NULL DEFAULT 'worker',
    implementation_ref TEXT,
    definition_hash TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliver_listener_edges (
    listener_id TEXT PRIMARY KEY,
    source_deliver_id TEXT NOT NULL,
    target_deliver_id TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'DELIVER_PASSED',
    context_selector TEXT,
    source_kind TEXT NOT NULL DEFAULT 'task_graph',
    edge_type TEXT NOT NULL DEFAULT 'listener',
    jev_gate INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_deliver_id) REFERENCES deliver_catalog(deliver_id),
    FOREIGN KEY(target_deliver_id) REFERENCES deliver_catalog(deliver_id)
);

CREATE INDEX IF NOT EXISTS idx_listener_target ON deliver_listener_edges(target_deliver_id, enabled);

CREATE TABLE IF NOT EXISTS context_sources (
    source_key TEXT PRIMARY KEY,
    task_id TEXT,
    origin_kind TEXT NOT NULL,
    origin_ref TEXT NOT NULL,
    graph_entity_id TEXT,
    graph_revision TEXT,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_context_task ON context_sources(task_id, active);

CREATE TABLE IF NOT EXISTS jev_route_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    route_kind TEXT NOT NULL,
    task_id TEXT,
    state_fingerprint TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    selected_id TEXT,
    probabilities_json TEXT,
    confidence REAL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_kind TEXT,
    fallback_id TEXT,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    request_preview_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jev_route_created ON jev_route_decisions(created_at DESC);

CREATE TABLE IF NOT EXISTS jev_usage_requests (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost REAL,
    unit TEXT NOT NULL,
    uncertain INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jev_usage_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    state TEXT NOT NULL,
    basis TEXT NOT NULL,
    unit TEXT NOT NULL,
    consumed REAL,
    remaining REAL,
    remaining_fraction REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jev_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    previous_state TEXT,
    state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    notified_at TEXT
);

CREATE TABLE IF NOT EXISTS deliver_economics (
    deliver_id TEXT PRIMARY KEY,
    currency TEXT NOT NULL DEFAULT 'USD',
    fixed_price REAL,
    valuation_amount REAL,
    valuation_as_of TEXT,
    valuation_source_url TEXT,
    valuation_basis TEXT,
    budget_allocated REAL,
    budget_reserved REAL NOT NULL DEFAULT 0,
    budget_spent REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'UNPRICED',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(deliver_id) REFERENCES deliver_catalog(deliver_id)
);
