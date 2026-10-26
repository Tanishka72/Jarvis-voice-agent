"""API keys: creating and checking them.

The plain key is shown ONCE, when it is created. The database keeps only its SHA-256 hash.
A fast hash is fine here because the keys are long and random; human passwords would need
a slow hash like bcrypt instead.
"""
import hashlib
import secrets

from backend.repositories import ApiKeyRepository


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AuthService:
    def __init__(self, keys: ApiKeyRepository):
        self.keys = keys
        self.db = keys.db

    def create_key(self, name: str) -> tuple[int, str]:
        key = "jv_" + secrets.token_urlsafe(32)
        with self.db:  # transaction: commit on success, roll back on error
            row = self.keys.create(name, hash_key(key))
        return row["id"], key

    def authenticate(self, key: str | None) -> int | None:
        """Return the API key's id, or None if the key is missing, wrong or revoked."""
        if not key:
            return None
        row = self.keys.find_active_by_hash(hash_key(key))
        return row["id"] if row else None
