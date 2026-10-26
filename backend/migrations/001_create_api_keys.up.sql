-- Who may call the API. We store a SHA-256 hash of each key, never the key itself,
-- so a stolen database file can't be used to call the API.
CREATE TABLE api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at  TEXT                                     -- NULL = still active
);
