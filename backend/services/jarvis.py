"""The bridge between the API and Jarvis's brain (agent.Brain), the same brain the desktop app uses.

STATEFUL vs STATELESS
  agent.Brain is stateful: it keeps the chat in memory, which is fine for one person at one
  desktop. An API must be stateless: any request can come for any conversation, and after a
  restart nothing in memory is left. So for every request we rebuild the chat from the
  messages saved in the database, ask the question, and keep nothing in memory afterwards.
  The database holds the state, not the server.
"""
import logging
import threading

import agent
import rag
import tools
from backend.services.answer_cache import AnswerCache

logger = logging.getLogger("jarvis.brain")

# On a server, Jarvis must not open or close apps, set desktop pop-ups or read the
# battery of the machine it runs on. Only these tools are offered to Gemini.
SERVER_TOOLS = [
    tools.get_weather, tools.get_weather_forecast, tools.get_current_time, tools.calculate,
    tools.wikipedia_summary, tools.convert_currency, rag.search_documents, rag.list_documents,
]

# rag.py keeps the current question's search traces in module-level variables, so only
# one question may use it at a time. Fine for a personal server; a big service would
# move that state into each request.
RAG_LOCK = threading.Lock()


class JarvisBrain:
    def __init__(self):
        self._brain = None

    def reply(self, history: list[tuple[str, str]], question: str) -> tuple[str, float | None, bool]:
        """Answer `question`, given the earlier (role, text) messages.
        Returns (answer, groundedness, from_cache)."""
        from backend.errors import ServiceUnavailableError

        with RAG_LOCK:
            if self._brain is None:
                try:
                    # Same saved answers as the desktop app (same database).
                    self._brain = agent.Brain(SERVER_TOOLS, answer_cache=AnswerCache())
                except SystemExit as e:  # Brain exits when .env has no Gemini key
                    raise ServiceUnavailableError(str(e)) from None
            self._brain.load_history(agent.to_contents(history))
            self._brain.last_check = None
            answer = self._brain.ask(question, log=logger.info)
            check = self._brain.last_check or {}
            return answer, check.get("groundedness"), self._brain.last_from_cache
