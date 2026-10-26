import sqlite3

from fastapi import APIRouter, Depends

from backend import migrate
from backend.cache import TTLCache
from backend.dependencies import get_cache, get_db
from backend.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: sqlite3.Connection = Depends(get_db), cache: TTLCache = Depends(get_cache)):
    """Is the server alive and is the database ready? Public: monitoring tools call this every few seconds."""
    pending = migrate.pending(db)
    return {"status": "degraded" if pending else "ok", "database": "ok",
            "pending_migrations": pending, "cache": cache.stats()}
