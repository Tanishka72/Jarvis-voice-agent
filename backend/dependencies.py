"""Dependency injection: how each controller gets the objects it needs.

FastAPI calls these functions for every request and passes the results to the controller
(through Depends(...)). Because controllers never build their own services, tests can
swap any of them for a fake with app.dependency_overrides, e.g. a fake Jarvis that
doesn't spend Gemini quota.
"""
import sqlite3
from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from backend.cache import TTLCache
from backend.database import connect
from backend.repositories import ConversationRepository, MessageRepository, UploadRepository
from backend.services.chat_service import ChatService
from backend.services.document_service import DocumentService
from backend.services.jarvis import JarvisBrain
from backend.services.weather_service import WeatherService

# Created once and shared by all requests.
app_cache = TTLCache()
_jarvis = JarvisBrain()

# AuthMiddleware does the real check. This only adds the "Authorize" button to /docs.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db() -> Iterator[sqlite3.Connection]:
    """One connection per request, always closed at the end, even after an error."""
    db = connect()
    try:
        yield db
    finally:
        db.close()


def get_cache() -> TTLCache:
    return app_cache


def get_jarvis() -> JarvisBrain:
    return _jarvis


def current_owner(request: Request) -> int:
    return request.state.api_key_id  # set by AuthMiddleware


def get_chat_service(db: sqlite3.Connection = Depends(get_db), jarvis: JarvisBrain = Depends(get_jarvis)) -> ChatService:
    return ChatService(ConversationRepository(db), MessageRepository(db), jarvis)


def get_document_service(db: sqlite3.Connection = Depends(get_db), cache: TTLCache = Depends(get_cache)) -> DocumentService:
    return DocumentService(UploadRepository(db), cache)


def get_weather_service(cache: TTLCache = Depends(get_cache)) -> WeatherService:
    return WeatherService(cache)
