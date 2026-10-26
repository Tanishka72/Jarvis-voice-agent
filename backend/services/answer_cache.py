"""Saved answers: ask the same question again, even days later, and Jarvis answers instantly
without calling Gemini (about 8 seconds -> a few milliseconds, and no quota used).

Unlike backend/cache.py (in memory, gone on restart), these answers are stored in the
database (table answer_cache), so they survive restarts. The desktop app and the API
share them.

A cache must never give a WRONG answer, so only answers that can't go out of date are saved:
  - not weather, time, currency, news...: they change (CHANGING_WORDS, and their tools
    aren't in CACHEABLE_TOOLS)
  - not actions like "open notepad": they must really run again
  - not follow-ups like "how can I prevent it?": "it" means something different in each chat
  - PDF answers are dropped automatically when your PDFs change (docs_version)
  - and every saved answer expires after MAX_AGE_DAYS
"""
import logging
import re
import sqlite3

from backend.database import connect
from backend.repositories import AnswerCacheRepository

logger = logging.getLogger("jarvis.memory")

MAX_AGE_DAYS = 30
# Tools whose results don't change from day to day. An answer that used any OTHER tool is never saved.
CACHEABLE_TOOLS = {"search_documents", "list_documents", "wikipedia_summary", "calculate"}
DOCUMENT_TOOLS = {"search_documents", "list_documents"}
# Words that make a question depend on the conversation ("it", "that one"...).
CONTEXT_WORDS = {"it", "its", "this", "that", "these", "those", "they", "them", "their", "he", "she", "him",
                 "her", "his", "there", "previous", "earlier", "last", "above", "again", "same", "else", "more"}
# Words whose answer changes over time, even if Gemini answers without a tool.
CHANGING_WORDS = {"today", "tonight", "tomorrow", "yesterday", "now", "latest", "news", "weather", "price",
                  "battery", "remind", "reminder", "timer", "open", "close"}

_LEADING_FILLER = re.compile(r"^(?:(?:hey|hi|hello|ok|okay)\s+)?(?:jarvis\s+)?"
                             r"(?:(?:please|can you|could you|would you|will you)\s+)*(?:tell me\s+)?")


def normalize(question: str) -> str:
    """One standard form, so small differences still match:
    "Hey Jarvis, can you tell me what is Overfitting?" and "what is overfitting" -> "what is overfitting"."""
    text = re.sub(r"[^\w\s%+*/.^-]", " ", question.lower())  # drop punctuation, keep maths symbols
    text = " ".join(text.split()).strip(" .")
    text = _LEADING_FILLER.sub("", text)
    return re.sub(r"\s+please$", "", text)


def is_reusable(key: str) -> bool:
    words = key.split()
    return len(words) >= 3 and not (set(words) & (CONTEXT_WORDS | CHANGING_WORDS))


def _docs_version() -> int:
    """How many PDF chunks are indexed. It changes whenever a PDF is added, changed or removed."""
    import rag
    return rag._get_collection().count()


class AnswerCache:
    """Each method opens its own short database connection, so it is safe to use from any thread."""

    def lookup(self, question: str) -> tuple[str, float | None] | None:
        """Return (answer, groundedness) if this question was answered before, else None."""
        key = normalize(question)
        if not is_reusable(key):
            return None
        try:
            db = connect()
            try:
                repo = AnswerCacheRepository(db)
                row = repo.get_fresh(key, MAX_AGE_DAYS)
                if row is None:
                    return None
                if row["docs_version"] is not None and row["docs_version"] != _docs_version():
                    return None  # your PDFs changed since then: the old answer may be wrong
                with db:
                    repo.record_hit(key)
                return row["answer"], row["groundedness"]
            finally:
                db.close()
        except sqlite3.Error:
            # A broken cache must never break Jarvis: just answer normally ("fail open").
            logger.exception("Answer cache lookup failed")
            return None

    def store(self, question: str, answer: str, tools_used: list[str], groundedness: float | None) -> bool:
        """Save the answer if it's safe to reuse later. Returns True if it was saved."""
        key = normalize(question)
        tools = set(tools_used)
        if not is_reusable(key) or not tools <= CACHEABLE_TOOLS or answer.startswith("Sorry"):
            return False
        try:
            docs_version = _docs_version() if tools & DOCUMENT_TOOLS else None
            db = connect()
            try:
                with db:
                    AnswerCacheRepository(db).save(key, question, answer, ",".join(sorted(tools)),
                                                   docs_version, groundedness)
                return True
            finally:
                db.close()
        except sqlite3.Error:
            logger.exception("Answer cache store failed")
            return False

    def count(self) -> int:
        try:
            db = connect()
            try:
                return AnswerCacheRepository(db).count()
            finally:
                db.close()
        except sqlite3.Error:
            return 0
