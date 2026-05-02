"""
RAG API Keys Repository

CRUD for the rag_api_keys collection used by the public langrag.ai API.
Keys are stored hashed (HMAC-SHA-256 with a server-side pepper); the plaintext
is only ever returned at issue time.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import COLLECTION_RAG_API_KEYS, RAG_API_KEY_PREFIX
from custom_types.field_keys import RAGApiKeyKeys as Keys
from db.repositories.base import BaseRepository
from rag.auth.hashing import hash_api_key

logger = logging.getLogger(__name__)


class RAGApiKeysRepository(BaseRepository):
    """Repository for RAG API keys."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_API_KEYS)

    async def issue_key(
        self,
        name: str,
        owner: str,
        scopes: list[str] | None = None,
    ) -> tuple[str, str]:
        """
        Issue a fresh API key.

        Returns (key_id, plaintext_key). The plaintext is only available at issue time;
        callers must capture and persist it themselves.
        """
        key_id = str(uuid.uuid4())
        plaintext = f"{RAG_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        document = {
            Keys.KEY_ID: key_id,
            Keys.KEY_HASH: hash_api_key(plaintext),
            Keys.NAME: name,
            Keys.OWNER: owner,
            Keys.SCOPES: scopes or [],
            Keys.ENABLED: True,
            Keys.CREATED_AT: datetime.now(UTC),
            Keys.LAST_USED_AT: None,
            Keys.EXPIRES_AT: None,
        }
        await self.create(document)
        logger.info(f"Issued RAG API key: key_id={key_id}, name={name}, owner={owner}")
        return key_id, plaintext

    async def find_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        """Find an enabled API key by hash."""
        return await self.find_one({Keys.KEY_HASH: key_hash, Keys.ENABLED: True})

    async def revoke(self, key_id: str) -> bool:
        """Disable an API key. Returns True if a record was modified."""
        updated = await self.update_one(
            {Keys.KEY_ID: key_id},
            {"$set": {Keys.ENABLED: False}},
        )
        return updated > 0

    async def touch_last_used(self, key_id: str) -> None:
        """Best-effort update of last_used_at; failures are swallowed (non-critical path)."""
        try:
            await self.update_one(
                {Keys.KEY_ID: key_id},
                {"$set": {Keys.LAST_USED_AT: datetime.now(UTC)}},
            )
        except Exception as e:
            logger.warning(f"Failed to update last_used_at for key_id={key_id}: {e}")

    async def list_keys(self) -> list[dict[str, Any]]:
        """List all API keys (without plaintext, hashes only)."""
        keys = await self.find_many({}, sort=[(Keys.CREATED_AT, -1)])
        for k in keys:
            k.pop("_id", None)
            k.pop(Keys.KEY_HASH, None)
        return keys
