import sqlite3


class ApiKeyRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def create(self, name: str, key_hash: str) -> sqlite3.Row:
        return self.db.execute(
            "INSERT INTO api_keys (name, key_hash) VALUES (?, ?) RETURNING id, name, created_at",
            (name, key_hash),
        ).fetchall()[0]

    def find_active_by_hash(self, key_hash: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT id, name FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (key_hash,)
        ).fetchone()

    def find_active_by_name(self, name: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT id, name FROM api_keys WHERE name = ? AND revoked_at IS NULL ORDER BY id LIMIT 1", (name,)
        ).fetchone()

    def list_all(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT id, name, created_at, revoked_at FROM api_keys ORDER BY id").fetchall()

    def revoke(self, key_id: int) -> bool:
        cur = self.db.execute(
            "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP WHERE id = ? AND revoked_at IS NULL", (key_id,))
        return cur.rowcount == 1
