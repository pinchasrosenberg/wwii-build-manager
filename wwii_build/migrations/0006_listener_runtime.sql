ALTER TABLE deliver_catalog ADD COLUMN availability TEXT NOT NULL DEFAULT 'available';

ALTER TABLE deliver_listener_edges ADD COLUMN proposal_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_listener_source_event
ON deliver_listener_edges(source_deliver_id, event_type, edge_type, jev_gate, enabled);

CREATE TABLE IF NOT EXISTS episode_build_states (
    episode_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0,
    objective TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'DISCOVERY',
    episode_state_json TEXT NOT NULL DEFAULT '{}',
    build_state_json TEXT NOT NULL DEFAULT '{}',
    context_refs_json TEXT NOT NULL DEFAULT '[]',
    updated_by_deliver_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(updated_by_deliver_id) REFERENCES deliver_catalog(deliver_id)
);

CREATE TABLE IF NOT EXISTS deliver_state_events (
    event_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    source_deliver_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    context_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ROUTING',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(episode_id) REFERENCES episode_build_states(episode_id),
    FOREIGN KEY(source_deliver_id) REFERENCES deliver_catalog(deliver_id)
);

CREATE INDEX IF NOT EXISTS idx_deliver_events_episode
ON deliver_state_events(episode_id, created_at DESC);

CREATE TABLE IF NOT EXISTS listener_activations (
    activation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    listener_id TEXT NOT NULL,
    source_deliver_id TEXT NOT NULL,
    target_deliver_id TEXT NOT NULL,
    jev_request_id TEXT NOT NULL,
    selected_state_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'SELECTED',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(event_id, listener_id),
    FOREIGN KEY(event_id) REFERENCES deliver_state_events(event_id),
    FOREIGN KEY(listener_id) REFERENCES deliver_listener_edges(listener_id),
    FOREIGN KEY(source_deliver_id) REFERENCES deliver_catalog(deliver_id),
    FOREIGN KEY(target_deliver_id) REFERENCES deliver_catalog(deliver_id),
    FOREIGN KEY(jev_request_id) REFERENCES jev_route_decisions(request_id)
);

CREATE INDEX IF NOT EXISTS idx_listener_activation_status
ON listener_activations(status, created_at);
