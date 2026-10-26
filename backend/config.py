"""Settings for the API server. Read from .env (the same file the desktop Jarvis uses),
so nothing secret is written in the code."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE / "data" / "jarvis.db"))

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))  # per API key
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
HISTORY_MESSAGES = 20  # earlier messages sent to Gemini with each new question

WEATHER_CACHE_SECONDS = 600     # weather changes slowly: 10 minutes
DOCUMENTS_CACHE_SECONDS = 300   # also cleared as soon as a new PDF finishes indexing
