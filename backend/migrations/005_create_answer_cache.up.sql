-- Saved answers: the same question asked again (even days later) is answered instantly,
-- without calling Gemini. Shared by the desktop app and the API.
CREATE TABLE answer_cache (
    question_key  TEXT PRIMARY KEY,          -- the question, normalised ("Hey Jarvis, what is X?" -> "what is x")
    question      TEXT NOT NULL,             -- as it was first asked
    answer        TEXT NOT NULL,
    tools_used    TEXT NOT NULL DEFAULT '',  -- e.g. "search_documents"
    docs_version  INTEGER,                   -- number of PDF chunks when saved; NULL if no PDF was used
    groundedness  REAL,
    hits          INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_hit_at   TEXT
);
