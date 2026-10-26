"""Repositories: the ONLY place that writes SQL. One class per table.

They don't know about HTTP or business rules; they just read and write rows.
Values are always passed as ? parameters, never pasted into the SQL text,
which is what makes SQL injection impossible.
"""
from backend.repositories.answer_cache_repository import AnswerCacheRepository
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.repositories.conversation_repository import ConversationRepository
from backend.repositories.message_repository import MessageRepository
from backend.repositories.upload_repository import UploadRepository

__all__ = ["AnswerCacheRepository", "ApiKeyRepository", "ConversationRepository", "MessageRepository",
           "UploadRepository"]
