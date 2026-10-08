-- Dashboard conversation about the manager state (immediate, read-only, outside the task queue).
CREATE TABLE IF NOT EXISTS state_chat_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id   INTEGER NOT NULL,
    role              TEXT NOT NULL,          -- user | assistant
    content           TEXT NOT NULL,
    model_key         TEXT,                   -- user turn: chosen key or NULL (automatic), assistant: key used
    provider          TEXT,
    model             TEXT,
    created_at        TEXT NOT NULL,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    reported_cost_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_state_chat_conv ON state_chat_messages(conversation_id, id);
