"""Long-term memory for the desktop app (voice and typing).

Every question and answer is saved in data/jarvis.db, in one ongoing conversation that belongs
to a built-in "Desktop app (voice)" owner. When Jarvis starts, it reloads the last messages, so
it still knows what you talked about yesterday. It uses the same tables as the API: the desktop
app is simply another client of the same database.
"""
import secrets

from backend import migrate
from backend.database import connect
from backend.repositories import ApiKeyRepository, ConversationRepository, MessageRepository
from backend.services.auth_service import hash_key

DESKTOP_OWNER = "Desktop app (voice)"
DESKTOP_TITLE = "Voice chats"
HISTORY_MESSAGES = 20  # how many earlier messages Jarvis reloads at start


class DesktopMemory:
    def __init__(self):
        db = connect()
        try:
            migrate.up(db)  # the desktop app prepares its own database: no commands to run
            keys, conversations = ApiKeyRepository(db), ConversationRepository(db)
            with db:
                owner = keys.find_active_by_name(DESKTOP_OWNER)
                if owner is None:
                    # A random key that is never shown, so this owner can't be used to call the API.
                    owner = keys.create(DESKTOP_OWNER, hash_key(secrets.token_urlsafe(32)))
                latest = conversations.list_for_owner(owner["id"], limit=1, offset=0)
                conversation = latest[0] if latest else conversations.create(owner["id"], DESKTOP_TITLE)
            self.conversation_id = conversation["id"]
        finally:
            db.close()

    def history(self, limit: int = HISTORY_MESSAGES) -> list[tuple[str, str]]:
        db = connect()
        try:
            return [(m["role"], m["content"]) for m in MessageRepository(db).latest(self.conversation_id, limit)]
        finally:
            db.close()

    def save(self, question: str, answer: str, groundedness: float | None = None) -> None:
        db = connect()
        try:
            with db:  # question and answer are saved together
                messages = MessageRepository(db)
                messages.add(self.conversation_id, "user", question)
                messages.add(self.conversation_id, "assistant", answer, groundedness)
                ConversationRepository(db).touch(self.conversation_id)
        finally:
            db.close()
