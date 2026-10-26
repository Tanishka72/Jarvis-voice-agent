"""Conversations with Jarvis: create, list, read, delete, and send a message."""
from backend import config
from backend.errors import NotFoundError
from backend.repositories import ConversationRepository, MessageRepository
from backend.services.jarvis import JarvisBrain

DEFAULT_TITLE = "New chat"


class ChatService:
    def __init__(self, conversations: ConversationRepository, messages: MessageRepository, jarvis: JarvisBrain):
        self.conversations = conversations
        self.messages = messages
        self.jarvis = jarvis
        self.db = conversations.db

    def create(self, owner_id: int, title: str | None):
        with self.db:
            return self.conversations.create(owner_id, title or DEFAULT_TITLE)

    def list(self, owner_id: int, limit: int, offset: int):
        return self.conversations.list_for_owner(owner_id, limit, offset), self.conversations.count_for_owner(owner_id)

    def get(self, owner_id: int, conversation_id: int):
        conversation = self._owned(owner_id, conversation_id)
        return conversation, self.messages.list_for_conversation(conversation_id)

    def delete(self, owner_id: int, conversation_id: int) -> None:
        with self.db:
            if not self.conversations.delete(conversation_id, owner_id):
                raise NotFoundError(f"Conversation {conversation_id} not found.")

    def send_message(self, owner_id: int, conversation_id: int, text: str):
        conversation = self._owned(owner_id, conversation_id)
        history = [(m["role"], m["content"]) for m in self.messages.latest(conversation_id, config.HISTORY_MESSAGES)]

        # Gemini can take several seconds, so call it BEFORE opening the transaction:
        # keep transactions short so they don't block other writers.
        answer, groundedness, from_cache = self.jarvis.reply(history, text)

        with self.db:  # both messages are saved together, or neither is
            question = self.messages.add(conversation_id, "user", text)
            reply = self.messages.add(conversation_id, "assistant", answer, groundedness)
            if conversation["title"] == DEFAULT_TITLE:
                self.conversations.rename(conversation_id, text if len(text) <= 50 else text[:50].rstrip() + "...")
            self.conversations.touch(conversation_id)
        return question, reply, from_cache

    def _owned(self, owner_id: int, conversation_id: int):
        conversation = self.conversations.get(conversation_id, owner_id)
        if conversation is None:
            # 404, not 403: don't even reveal that someone else's conversation exists.
            raise NotFoundError(f"Conversation {conversation_id} not found.")
        return conversation
