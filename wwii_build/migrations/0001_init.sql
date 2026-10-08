-- WWII Build Manager: initial schema.
-- Timestamps are ISO-8601 UTC strings. JSON columns hold compact JSON text.

CREATE TABLE tasks (
    task_id            TEXT PRIMARY KEY,
    packet             TEXT NOT NULL,
    owner              TEXT NOT NULL,
    domain             TEXT,
    mode               TEXT NOT NULL,
    model_profile      TEXT NOT NULL,
    lego_ids           TEXT NOT NULL DEFAULT '[]',
    write_scope        TEXT NOT NULL DEFAULT '[]',
    context_entry      TEXT,
    brief_path         TEXT,
    note               TEXT,
    acceptance         TEXT NOT NULL DEFAULT '[]',   -- task-specific commands from overlay
    extra              TEXT NOT NULL DEFAULT '{}',   -- overlay extras (evidence, required_paths...)
    definition_hash    TEXT NOT NULL,
    wave               INTEGER NOT NULL DEFAULT 0,
    state              TEXT NOT NULL DEFAULT 'PENDING',
    state_reason       TEXT,
    not_before         TEXT,                          -- retry backoff / quota wake time
    attempts_count     INTEGER NOT NULL DEFAULT 0,    -- real (non-quota) attempts
    failed_attempts    INTEGER NOT NULL DEFAULT 0,
    last_model_key     TEXT,
    preferred_model_key TEXT,                         -- user "change provider"
    branch             TEXT,
    worktree           TEXT,
    passed_commit      TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE task_dependencies (
    task_id    TEXT NOT NULL REFERENCES tasks(task_id),
    depends_on TEXT NOT NULL REFERENCES tasks(task_id),
    PRIMARY KEY (task_id, depends_on)
);

CREATE TABLE task_attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id),
    kind                TEXT NOT NULL DEFAULT 'execute',   -- execute | review
    attempt_no          INTEGER NOT NULL,
    provider            TEXT NOT NULL,
    model_key           TEXT NOT NULL,
    model               TEXT NOT NULL,
    effort              TEXT,
    status              TEXT NOT NULL,                     -- RUNNING, SUCCEEDED, FAILED_ATTEMPT, QUOTA_LIMITED, ...
    failure_class       TEXT,
    diagnosis           TEXT,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    exit_code           INTEGER,
    signal              INTEGER,
    pid                 INTEGER,
    pgid                INTEGER,
    process_started     TEXT,
    cwd                 TEXT,
    command             TEXT,             -- sanitized argv JSON
    stdout_path         TEXT,
    stderr_path         TEXT,
    last_message_path   TEXT,
    context_pack_id     INTEGER,
    base_commit         TEXT,
    head_commit         TEXT,
    session_id          TEXT,
    input_tokens        INTEGER,
    cached_input_tokens INTEGER,
    output_tokens       INTEGER,
    reported_cost_usd   REAL,
    quota_before        TEXT,
    quota_after         TEXT,
    handoff             TEXT,             -- parsed TaskResult JSON (or NULL)
    handoff_status      TEXT              -- VALID | MALFORMED | MISSING
);
CREATE INDEX idx_attempts_task ON task_attempts(task_id);

CREATE TABLE workers (
    attempt_id     INTEGER PRIMARY KEY REFERENCES task_attempts(id),
    task_id        TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    pid            INTEGER,
    pgid           INTEGER,
    process_started TEXT,
    worktree       TEXT,
    started_at     TEXT NOT NULL,
    context_bytes  INTEGER,
    daemon_pid     INTEGER
);

CREATE TABLE provider_state (
    provider         TEXT NOT NULL,
    account          TEXT NOT NULL DEFAULT 'default',
    family           TEXT NOT NULL DEFAULT '*',
    status           TEXT NOT NULL DEFAULT 'UNKNOWN',
    blocked_until    TEXT,
    session_reset_at TEXT,
    weekly_reset_at  TEXT,
    used_percent     REAL,            -- only when the CLI reports it machine-readably
    window_minutes   INTEGER,
    backoff_level    INTEGER NOT NULL DEFAULT 0,
    last_checked_at  TEXT,
    last_success_at  TEXT,
    last_limit_event TEXT,
    confidence       TEXT NOT NULL DEFAULT 'none',   -- none | low | medium | high
    source           TEXT,
    detail           TEXT,
    PRIMARY KEY (provider, account, family)
);

CREATE TABLE quota_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    provider    TEXT NOT NULL,
    family      TEXT NOT NULL DEFAULT '*',
    kind        TEXT NOT NULL,     -- LIMIT_HIT, SNAPSHOT, RESET_PASSED, WARNING, AUTH_ERROR, ...
    window      TEXT,              -- session | weekly | model | unknown
    reset_at    TEXT,
    attempt_id  INTEGER,
    source      TEXT,
    raw         TEXT
);

CREATE TABLE context_packs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    manifest    TEXT NOT NULL,     -- JSON: inline/reference/excluded items with hashes
    prompt_path TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    total_bytes INTEGER NOT NULL
);

CREATE TABLE artifacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    attempt_id  INTEGER,
    kind        TEXT NOT NULL,     -- screenshot | video | test_scene | preview_3d | report | diff | log | other
    path        TEXT NOT NULL,     -- stored copy under state dir
    source_path TEXT,
    description TEXT,
    sha256      TEXT,
    bytes       INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE test_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    attempt_id  INTEGER,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,     -- builtin | command
    passed      INTEGER NOT NULL,
    exit_code   INTEGER,
    duration_s  REAL,
    output_tail TEXT,
    commit_sha  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    attempt_id  INTEGER,
    reviewer    TEXT NOT NULL,     -- human | deterministic | <provider:model>
    verdict     TEXT NOT NULL,     -- approve | changes_requested | reject
    findings    TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    kind        TEXT NOT NULL,     -- model | review | escalation | astra_recommended | dependency_change | billing
    subject     TEXT,              -- e.g. model key
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    reason      TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);
CREATE INDEX idx_approvals_task ON approvals(task_id, status);

CREATE TABLE capability_gaps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    attempt_id  INTEGER,
    kind        TEXT NOT NULL,     -- capability_gap | cross_domain_request | uncertainty
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE control_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    command     TEXT NOT NULL,     -- pause | resume | stop | kill | retry | skip | approve | reject | set_provider | refresh
    args        TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT 'cli',
    handled_at  TEXT,
    result      TEXT
);

CREATE TABLE scheduler_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE event_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    event    TEXT NOT NULL,
    task_id  TEXT,
    attempt_id INTEGER,
    provider TEXT,
    detail   TEXT
);
CREATE INDEX idx_events_task ON event_log(task_id);
