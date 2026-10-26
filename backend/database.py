"""Connections to the SQLite database (data/jarvis.db).

SQLite is a real SQL database kept in one file, so there is no server to install. The SQL in
this project (CREATE TABLE, JOIN, GROUP BY, RETURNING...) works almost unchanged on PostgreSQL.
"""
import sqlite3
from pathlib import Path

from backend import config


def connect() -> sqlite3.Connection:
    path = Path(config.DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may open the connection in one worker thread
    # and use it in another during the same request.
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows work like dicts: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores REFERENCES ... unless this is on
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't wait for the writer
    return conn
