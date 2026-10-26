-- Chats with Jarvis. Each conversation belongs to one API key (its owner).
CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id  INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- "My conversations, newest first" is the most common query, so index exactly that.
CREATE INDEX idx_conversations_owner ON conversations (api_key_id, updated_at);

-- One row per message. Deleting a conversation deletes its messages (ON DELETE CASCADE).
CREATE TABLE messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_messages_conversation ON messages (conversation_id, id);
