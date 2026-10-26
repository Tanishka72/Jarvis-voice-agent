import sqlite3


class AnswerCacheRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get_fresh(self, key: str, max_age_days: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT answer, tools_used, docs_version, groundedness FROM answer_cache "
            "WHERE question_key = ? AND created_at >= datetime('now', ?)",
            (key, f"-{max_age_days} days"),
        ).fetchone()

    def save(self, key: str, question: str, answer: str, tools_used: str,
             docs_version: int | None, groundedness: float | None) -> None:
        # "Upsert": insert, or replace the old answer if this question was saved before.
        self.db.execute(
            "INSERT INTO answer_cache (question_key, question, answer, tools_used, docs_version, groundedness) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (question_key) DO UPDATE SET question = excluded.question, answer = excluded.answer, "
            "tools_used = excluded.tools_used, docs_version = excluded.docs_version, "
            "groundedness = excluded.groundedness, hits = 0, created_at = CURRENT_TIMESTAMP, last_hit_at = NULL",
            (key, question, answer, tools_used, docs_version, groundedness),
        )

    def record_hit(self, key: str) -> None:
        self.db.execute("UPDATE answer_cache SET hits = hits + 1, last_hit_at = CURRENT_TIMESTAMP "
                        "WHERE question_key = ?", (key,))

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0]

    def most_used(self, limit: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT question, hits, created_at FROM answer_cache ORDER BY hits DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def clear(self) -> int:
        return self.db.execute("DELETE FROM answer_cache").rowcount
