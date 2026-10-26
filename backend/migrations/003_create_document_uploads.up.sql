-- PDF uploads. Indexing a PDF takes up to a minute, so it runs in the background and
-- this table tracks its progress: pending -> indexing -> ready (or failed).
CREATE TABLE document_uploads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'indexing', 'ready', 'failed')),
    chunks       INTEGER,
    error        TEXT,
    uploaded_by  INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
