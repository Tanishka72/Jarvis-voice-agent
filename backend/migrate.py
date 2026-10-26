"""Database migrations: numbered SQL files in backend/migrations/.

    python -m backend.migrate up       apply every migration that hasn't run yet
    python -m backend.migrate down     undo the most recent migration
    python -m backend.migrate status   show which migrations have run

Every migration is a pair of files:
    002_create_conversations.up.sql    makes the change (CREATE TABLE ...)
    002_create_conversations.down.sql  undoes exactly that change (DROP TABLE ...)
The schema_migrations table remembers which ones have run, so each runs only once, in order.
Never edit a migration that has already run: add a new one instead (see 004).
"""
import sqlite3
import sys
from pathlib import Path

from backend.database import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                      version TEXT PRIMARY KEY,
                      applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def available() -> list[str]:
    return sorted(p.name.removesuffix(".up.sql") for p in MIGRATIONS_DIR.glob("*.up.sql"))


def applied(db: sqlite3.Connection) -> list[str]:
    _ensure_table(db)
    return [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]


def pending(db: sqlite3.Connection) -> list[str]:
    done = set(applied(db))
    return [v for v in available() if v not in done]


def _run(db: sqlite3.Connection, sql_file: Path, bookkeeping: str) -> None:
    """Run a migration and record it in ONE transaction: either both happen or neither does.
    (SQLite, like PostgreSQL, can roll back CREATE/DROP/ALTER TABLE.)"""
    script = f"BEGIN;\n{sql_file.read_text(encoding='utf-8')}\n{bookkeeping}\nCOMMIT;"
    try:
        db.executescript(script)
    except sqlite3.Error:
        if db.in_transaction:
            db.rollback()
        raise


def up(db: sqlite3.Connection) -> list[str]:
    done = []
    for version in pending(db):
        _run(db, MIGRATIONS_DIR / f"{version}.up.sql",
             f"INSERT INTO schema_migrations (version) VALUES ('{version}');")
        done.append(version)
    return done


def down(db: sqlite3.Connection) -> str | None:
    versions = applied(db)
    if not versions:
        return None
    version = versions[-1]
    _run(db, MIGRATIONS_DIR / f"{version}.down.sql",
         f"DELETE FROM schema_migrations WHERE version = '{version}';")
    return version


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    db = connect()
    try:
        if command == "up":
            done = up(db)
            print("\n".join(f"applied  {v}" for v in done) or "Already up to date.")
        elif command == "down":
            version = down(db)
            print(f"rolled back  {version}" if version else "Nothing to roll back.")
        elif command == "status":
            done = set(applied(db))
            for v in available():
                print(f"[{'x' if v in done else ' '}] {v}")
        else:
            print(__doc__)
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
