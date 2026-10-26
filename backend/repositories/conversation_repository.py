import sqlite3

# Every query that returns conversations also counts their messages (LEFT JOIN + GROUP BY),
# so a conversation with no messages still shows up, with message_count = 0.
_SELECT = """
    SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count
    FROM conversations c
    LEFT JOIN messages m ON m.conversation_id = c.id
"""


class ConversationRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def create(self, owner_id: int, title: str) -> sqlite3.Row:
        new_id = self.db.execute(
            "INSERT INTO conversations (api_key_id, title) VALUES (?, ?) RETURNING id", (owner_id, title)
        ).fetchall()[0]["id"]
        return self.get(new_id, owner_id)

    def get(self, conversation_id: int, owner_id: int) -> sqlite3.Row | None:
        # Filtering by owner here means one user can never read another user's chat.
        return self.db.execute(
            _SELECT + "WHERE c.id = ? AND c.api_key_id = ? GROUP BY c.id", (conversation_id, owner_id)
        ).fetchone()

    def list_for_owner(self, owner_id: int, limit: int, offset: int) -> list[sqlite3.Row]:
        return self.db.execute(
            _SELECT + "WHERE c.api_key_id = ? GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?",
            (owner_id, limit, offset),
        ).fetchall()

    def count_for_owner(self, owner_id: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM conversations WHERE api_key_id = ?", (owner_id,)).fetchone()[0]

    def rename(self, conversation_id: int, title: str) -> None:
        self.db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))

    def touch(self, conversation_id: int) -> None:
        self.db.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))

    def delete(self, conversation_id: int, owner_id: int) -> bool:
        cur = self.db.execute("DELETE FROM conversations WHERE id = ? AND api_key_id = ?", (conversation_id, owner_id))
        return cur.rowcount == 1
