"""Jarvis REST API: gives websites, phone apps and other programs the same brain the desktop
app uses (agent.py, tools.py, rag.py). This file only wires the pieces together.

    Run:   .venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload
    Docs:  http://127.0.0.1:8000/docs
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import rag
from backend import migrate
from backend.controllers import conversations, documents, health, weather
from backend.database import connect
from backend.errors import AppError, error_response
from backend.middlewares import AuthMiddleware, RateLimitMiddleware, RequestContextMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before the first request) and once at shutdown (after `yield`)."""
    db = connect()
    try:
        pending = migrate.pending(db)
    finally:
        db.close()
    if pending:
        # Fail fast: running new code on an old schema causes confusing errors later.
        raise RuntimeError(f"Database needs migrations {pending}. Run: python -m backend.migrate up")
    rag.on_event = logging.getLogger("jarvis.rag").info
    threading.Thread(target=rag.index_folder, daemon=True).start()  # index new PDFs, load the models
    yield


app = FastAPI(
    title="Jarvis API",
    version="1.0.0",
    description="Chat with Jarvis, search your PDFs and check the weather. "
                "Click **Authorize** and paste your API key (create one with `python -m backend.manage create-key NAME`).",
    lifespan=lifespan,
)

# The LAST middleware added runs FIRST, so this reads bottom-up: RequestContext -> Auth -> RateLimit.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(weather.router)


# ---------- every error gets the same JSON shape ----------
@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return error_response(request, exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or e["loc"][0], "message": e["msg"]}
               for e in exc.errors()]
    return error_response(request, 422, "validation_error", "Some input is invalid.", details)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return error_response(request, exc.status_code, code, str(exc.detail))
