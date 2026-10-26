import sqlite3

_COLUMNS = "id, role, content, groundedness, created_at"


class MessageRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def add(self, conversation_id: int, role: str, content: str, groundedness: float | None = None) -> sqlite3.Row:
        return self.db.execute(
            f"INSERT INTO messages (conversation_id, role, content, groundedness) VALUES (?, ?, ?, ?) "
            f"RETURNING {_COLUMNS}",
            (conversation_id, role, content, groundedness),
        ).fetchall()[0]

    def list_for_conversation(self, conversation_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            f"SELECT {_COLUMNS} FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        ).fetchall()

    def latest(self, conversation_id: int, limit: int) -> list[sqlite3.Row]:
        """The last `limit` messages, oldest first (a subquery picks them, the outer query re-orders)."""
        return self.db.execute(
            f"SELECT {_COLUMNS} FROM (SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?) "
            f"ORDER BY id",
            (conversation_id, limit),
        ).fetchall()
