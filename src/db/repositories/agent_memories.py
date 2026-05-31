"""
Agent Memories Repository

CRUD for the `agent_memories` collection — the long-term memory store for
the agent runtime. Every memory is owned by exactly one `user_id`; every
query MUST pre-filter on `user_id` before doing anything else.

Embeddings are stored as BSON Binary (subtype 9), matching the `rag_chunks`
convention so Atlas Vector Search can serve them without conversion.

See knowledge/plans/AGENTIC_CHATBOT_LAYER.md, sections A + B + C.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import (
    AGENT_EPISODIC_MEMORY_TTL_DAYS,
    COLLECTION_AGENT_MEMORIES,
    CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
    SCHEMA_VERSION_FIELD,
)
from custom_types.db_schemas import MemoryNamespace
from custom_types.field_keys import AgentMemoryKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AgentMemoriesRepository(BaseRepository):
    """Repository for agent long-term memories."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_AGENT_MEMORIES)

    async def create_memory(
        self,
        user_id: str,
        namespace: MemoryNamespace,
        content: str,
        embedding: Any,
        embedding_model: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        ttl_days: int | None = None,
    ) -> str:
        """Insert a single memory. Returns `memory_id`.

        `expires_at` is set only when `ttl_days` is provided; the caller for
        episodic memories should pass `ttl_days=AGENT_EPISODIC_MEMORY_TTL_DAYS`
        (or rely on the helper `episodic_ttl_days()` below). Semantic and
        procedural memories pass `ttl_days=None` so they persist indefinitely.
        """
        memory_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=ttl_days) if ttl_days is not None else None
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
            Keys.MEMORY_ID: memory_id,
            Keys.USER_ID: user_id,
            Keys.NAMESPACE: str(namespace),
            Keys.CONTENT: content,
            Keys.EMBEDDING: embedding,
            Keys.EMBEDDING_MODEL: embedding_model,
            Keys.IMPORTANCE: float(importance),
            Keys.METADATA: metadata or {},
            Keys.CREATED_AT: now,
            Keys.LAST_ACCESSED_AT: None,
            Keys.ACCESS_COUNT: 0,
            Keys.EXPIRES_AT: expires_at,
        }
        await self.create(document)
        logger.info(
            f"Created memory: memory_id={memory_id} user_id={user_id} "
            f"namespace={namespace} importance={importance:.2f}"
        )
        return memory_id

    async def find_by_memory_id(self, memory_id: str) -> dict[str, Any] | None:
        return await self.find_one({Keys.MEMORY_ID: memory_id})

    async def list_for_user(
        self,
        user_id: str,
        namespace: MemoryNamespace | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List a user's memories, newest first. Embeddings stripped for size."""
        query: dict[str, Any] = {Keys.USER_ID: user_id}
        if namespace is not None:
            query[Keys.NAMESPACE] = str(namespace)
        memories = await self.find_many(
            query,
            sort=[(Keys.CREATED_AT, -1)],
            limit=limit,
            projection={Keys.EMBEDDING: 0},
        )
        return memories

    async def touch_access(self, memory_id: str) -> None:
        """Best-effort bump of access stats after a successful retrieval."""
        try:
            await self.update_one(
                {Keys.MEMORY_ID: memory_id},
                {
                    "$set": {Keys.LAST_ACCESSED_AT: datetime.now(UTC)},
                    "$inc": {Keys.ACCESS_COUNT: 1},
                },
            )
        except Exception as e:
            logger.warning(f"touch_access failed: memory_id={memory_id} error={e}")

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """Delete a single memory. User-scoped to prevent cross-tenant deletion."""
        return await self.delete_one(
            {Keys.MEMORY_ID: memory_id, Keys.USER_ID: user_id},
        )

    async def delete_all_for_user(self, user_id: str) -> int:
        """GDPR purge: drop every memory owned by a user. Returns count."""
        return await self.delete_many({Keys.USER_ID: user_id})

    @staticmethod
    def episodic_ttl_days() -> int:
        """Default TTL for episodic memories (30 days, per project policy)."""
        return AGENT_EPISODIC_MEMORY_TTL_DAYS
