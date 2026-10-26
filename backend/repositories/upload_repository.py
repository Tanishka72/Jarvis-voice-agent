import sqlite3

_COLUMNS = "id, filename, status, chunks, error, created_at, updated_at"


class UploadRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def create(self, filename: str, owner_id: int) -> sqlite3.Row:
        return self.db.execute(
            f"INSERT INTO document_uploads (filename, uploaded_by) VALUES (?, ?) RETURNING {_COLUMNS}",
            (filename, owner_id),
        ).fetchall()[0]

    def get(self, upload_id: int) -> sqlite3.Row | None:
        return self.db.execute(f"SELECT {_COLUMNS} FROM document_uploads WHERE id = ?", (upload_id,)).fetchone()

    def set_status(self, upload_id: int, status: str, chunks: int | None = None, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE document_uploads SET status = ?, chunks = ?, error = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (status, chunks, error, upload_id),
        )
