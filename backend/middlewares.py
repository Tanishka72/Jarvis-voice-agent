"""Middlewares: code that runs around EVERY request, before and after the controller.

    request -> RequestContext -> Auth -> RateLimit -> controller
    response <- RequestContext <- Auth <- RateLimit <- controller

A middleware can stop a request early (Auth answers 401, RateLimit answers 429),
so the controller never runs.
"""
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from backend import config
from backend.database import connect
from backend.errors import error_response
from backend.repositories import ApiKeyRepository
from backend.services.auth_service import AuthService

logger = logging.getLogger("jarvis.api")

PUBLIC_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Gives each request an ID, times it, and writes one log line for it.

    The ID is sent back in the X-Request-ID header and inside error bodies, so a user
    can report "request a1b2c3 failed" and you can find exactly that line in the logs.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error [%s]", request_id)
            # Never send the real error text: it can reveal file paths, SQL or secrets.
            response = error_response(request, 500, "internal_error", "Something went wrong on our side.")
        ms = round((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{ms}ms"
        logger.info("%s %s -> %s in %sms [%s]", request.method, request.url.path, response.status_code, ms, request_id)
        return response


def _authenticate(key: str | None) -> int | None:
    db = connect()
    try:
        return AuthService(ApiKeyRepository(db)).authenticate(key)
    finally:
        db.close()


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication: who is calling? Every request except PUBLIC_PATHS needs a valid X-API-Key header."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        # The database call is blocking, so run it in a worker thread, not on the event loop.
        key_id = await run_in_threadpool(_authenticate, request.headers.get("X-API-Key"))
        if key_id is None:
            return error_response(request, 401, "unauthorized",
                                  "Missing or invalid API key. Send it in the X-API-Key header.")
        request.state.api_key_id = key_id  # controllers read this to know the owner
        return await call_next(request)


class SlidingWindowRateLimiter:
    """Each key may make `limit` requests in any 60-second window.

    Stored in memory, so it is STATEFUL: it resets on restart and isn't shared between
    server processes. Production setups keep these counters in Redis.
    """

    def __init__(self):
        self._hits: dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key_id: int, limit: int) -> tuple[bool, int]:
        """Return (allowed, remaining requests if allowed, or seconds to wait if not)."""
        now = time.monotonic()
        with self._lock:
            window = self._hits[key_id]
            while window and window[0] <= now - 60:
                window.popleft()  # forget requests older than 60 seconds
            if len(window) >= limit:
                return False, int(window[0] + 60 - now) + 1
            window.append(now)
            return True, limit - len(window)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = SlidingWindowRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects the server and your Gemini quota from one caller sending too many requests."""

    async def dispatch(self, request: Request, call_next):
        key_id = getattr(request.state, "api_key_id", None)
        if key_id is None:  # public path, nothing to count
            return await call_next(request)
        limit = config.RATE_LIMIT_PER_MINUTE
        allowed, number = rate_limiter.check(key_id, limit)
        if not allowed:
            response = error_response(request, 429, "rate_limited",
                                      f"Too many requests: the limit is {limit} per minute.")
            response.headers["Retry-After"] = str(number)
            return response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(number)
        return response
