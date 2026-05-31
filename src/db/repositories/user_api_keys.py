"""
User API Keys Repository

CRUD for the `user_api_keys` collection. Each row maps a hashed API key to a
specific user_id; the auth layer resolves an incoming key to its owning user
record before any tool runs.

Kept parallel to the existing `rag_api_keys` collection so the public RAG
auth path remains unchanged. See knowledge/plans/AGENTIC_CHATBOT_LAYER.md.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import (
    AGENT_USER_API_KEY_PREFIX,
    COLLECTION_USER_API_KEYS,
    CURRENT_SCHEMA_VERSION_USER_API_KEY,
    SCHEMA_VERSION_FIELD,
)
from custom_types.field_keys import UserApiKeyKeys as Keys
from db.repositories.base import BaseRepository
from rag.auth.hashing import hash_api_key

logger = logging.getLogger(__name__)


class UserApiKeysRepository(BaseRepository):
    """Repository for user-scoped API keys."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_USER_API_KEYS)

    async def issue_key(
        self,
        user_id: str,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[str, str]:
        """Issue a fresh API key bound to a user.

        Returns (key_id, plaintext_key). Plaintext is only available at issue
        time; callers must capture and persist it themselves.
        """
        key_id = str(uuid.uuid4())
        plaintext = f"{AGENT_USER_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER_API_KEY,
            Keys.KEY_ID: key_id,
            Keys.KEY_HASH: hash_api_key(plaintext),
            Keys.USER_ID: user_id,
            Keys.NAME: name,
            Keys.SCOPES: scopes or [],
            Keys.ENABLED: True,
            Keys.CREATED_AT: datetime.now(UTC),
            Keys.LAST_USED_AT: None,
            Keys.EXPIRES_AT: None,
        }
        await self.create(document)
        logger.info(f"Issued user API key: key_id={key_id} user_id={user_id} name={name}")
        return key_id, plaintext

    async def find_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        """Find an enabled API key by hash."""
        return await self.find_one({Keys.KEY_HASH: key_hash, Keys.ENABLED: True})

    async def find_by_key_id(self, key_id: str) -> dict[str, Any] | None:
        """Find a key by its stable key_id (regardless of enabled state)."""
        return await self.find_one({Keys.KEY_ID: key_id})

    async def revoke(self, key_id: str) -> bool:
        """Disable an API key. Returns True if a record was modified."""
        return await self.update_one(
            {Keys.KEY_ID: key_id},
            {"$set": {Keys.ENABLED: False}},
        )

    async def touch_last_used(self, key_id: str) -> None:
        """Best-effort update of last_used_at; failures are swallowed."""
        try:
            await self.update_one(
                {Keys.KEY_ID: key_id},
                {"$set": {Keys.LAST_USED_AT: datetime.now(UTC)}},
            )
        except Exception as e:
            logger.warning(f"touch_last_used failed: key_id={key_id} error={e}")

    async def list_keys_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """List keys belonging to a user (hashes stripped from output)."""
        keys = await self.find_many({Keys.USER_ID: user_id}, sort=[(Keys.CREATED_AT, -1)])
        for k in keys:
            k.pop("_id", None)
            k.pop(Keys.KEY_HASH, None)
        return keys
