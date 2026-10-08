-- Capabilities (group_name) and sub-capabilities (name) of a Deliver, discovered from its source by onboarding.
CREATE TABLE IF NOT EXISTS deliver_capabilities (
    capability_id  TEXT PRIMARY KEY,           -- <deliver_id>/<group>/<name>
    deliver_id     TEXT NOT NULL REFERENCES deliver_catalog(deliver_id),
    system_id      TEXT,
    group_name     TEXT NOT NULL,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,              -- files | py_functions | mcp_tools | http_routes | argparse | js_functions | declared
    source_ref     TEXT,
    description    TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capabilities_deliver ON deliver_capabilities(deliver_id, active, group_name);
