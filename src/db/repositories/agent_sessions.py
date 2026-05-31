"""
Agent Sessions Repository

CRUD for the `agent_sessions` collection. Each session row is the durable
metadata twin of a LangGraph checkpointer thread: `session_id == thread_id`.

Sliding TTL: `expires_at` is pushed forward on every turn via
`touch_session(...)`; abandoned sessions are auto-cleaned by MongoDB.

See knowledge/plans/AGENTIC_CHATBOT_LAYER.md, section A.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import (
    COLLECTION_AGENT_SESSIONS,
    CURRENT_SCHEMA_VERSION_AGENT_SESSION,
    SCHEMA_VERSION_FIELD,
)
from custom_types.field_keys import AgentSessionKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

# Default idle TTL for an agent session; surfaces via the sliding `expires_at`
# field on every turn. Aggressive enough to clean up forgotten tabs, lenient
# enough that an admin can step away for a meeting and resume.
DEFAULT_SESSION_TTL_HOURS = 24


class AgentSessionsRepository(BaseRepository):
    """Repository for agent chat session metadata."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_AGENT_SESSIONS)

    async def create_session(
        self,
        user_id: str,
        title: str = "",
        community_context: str | None = None,
        ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> str:
        """Create a new session row. Returns `session_id` (== LangGraph thread_id)."""
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_AGENT_SESSION,
            Keys.SESSION_ID: session_id,
            Keys.USER_ID: user_id,
            Keys.TITLE: title,
            Keys.COMMUNITY_CONTEXT: community_context,
            Keys.CREATED_AT: now,
            Keys.LAST_MESSAGE_AT: now,
            Keys.MESSAGE_COUNT: 0,
            Keys.COST_SO_FAR: {},
            Keys.EXPIRES_AT: now + timedelta(hours=ttl_hours),
        }
        await self.create(document)
        logger.info(f"Created agent session: session_id={session_id} user_id={user_id}")
        return session_id

    async def find_by_session_id(self, session_id: str) -> dict[str, Any] | None:
        return await self.find_one({Keys.SESSION_ID: session_id})

    async def find_for_user(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List sessions for a user, newest activity first."""
        return await self.find_many(
            {Keys.USER_ID: user_id},
            sort=[(Keys.LAST_MESSAGE_AT, -1)],
            limit=limit,
        )

    async def touch_session(
        self,
        session_id: str,
        ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> bool:
        """Slide `expires_at` forward and bump `last_message_at` + `message_count`."""
        now = datetime.now(UTC)
        return await self.update_one(
            {Keys.SESSION_ID: session_id},
            {
                "$set": {
                    Keys.LAST_MESSAGE_AT: now,
                    Keys.EXPIRES_AT: now + timedelta(hours=ttl_hours),
                },
                "$inc": {Keys.MESSAGE_COUNT: 1},
            },
        )

    async def update_cost(self, session_id: str, cost: dict[str, Any]) -> bool:
        """Replace the aggregated cost-so-far blob for the session."""
        return await self.update_one(
            {Keys.SESSION_ID: session_id},
            {"$set": {Keys.COST_SO_FAR: cost}},
        )

    async def delete_session(self, session_id: str) -> bool:
        """Delete the session row. Checkpointer cleanup is the caller's job."""
        return await self.delete_one({Keys.SESSION_ID: session_id})
