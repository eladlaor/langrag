"""
RAG Conversations Repository

CRUD operations for the rag_conversations collection (chat sessions with history).
"""

import logging
from datetime import datetime, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import COLLECTION_RAG_CONVERSATIONS
from custom_types.field_keys import RAGConversationKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ConversationsRepository(BaseRepository):
    """Repository for RAG conversation sessions."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_CONVERSATIONS)

    async def create_session(
        self,
        session_id: str,
        content_sources: list[str],
        title: str | None = None,
    ) -> str:
        """
        Create a new conversation session.

        Args:
            session_id: UUID for the session
            content_sources: List of content source types to search
            title: Optional session title (auto-generated from first query if None)

        Returns:
            session_id
        """
        now = datetime.now(UTC)
        document = {
            Keys.SESSION_ID: session_id,
            Keys.TITLE: title,
            Keys.CONTENT_SOURCES: content_sources,
            Keys.MESSAGES: [],
            Keys.CREATED_AT: now,
            Keys.UPDATED_AT: now,
        }
        await self.create(document)
        logger.info(f"Created RAG session: {session_id}")
        return session_id

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a session by ID."""
        return await self.find_by_id(Keys.SESSION_ID, session_id)

    async def append_message(
        self,
        session_id: str,
        message: dict[str, Any],
    ) -> bool:
        """
        Append a message to a session's history.

        Args:
            session_id: Session to update
            message: Message dict with message_id, role, content, citations, etc.

        Returns:
            True if updated
        """
        return await self.update_one(
            {Keys.SESSION_ID: session_id},
            {
                "$push": {Keys.MESSAGES: message},
                "$set": {Keys.UPDATED_AT: datetime.now(UTC)},
            },
        )

    async def update_title(self, session_id: str, title: str) -> bool:
        """Set or update session title (typically auto-generated from first query)."""
        return await self.update_one(
            {Keys.SESSION_ID: session_id},
            {"$set": {Keys.TITLE: title, Keys.UPDATED_AT: datetime.now(UTC)}},
        )

    async def list_sessions(
        self,
        limit: int = 20,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List sessions ordered by most recently updated.

        Returns session metadata without full message history (for listing UI).
        Uses aggregation pipeline because $size expressions require $project stage.
        """
        pipeline = [
            {"$sort": {Keys.UPDATED_AT: -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    Keys.SESSION_ID: 1,
                    Keys.TITLE: 1,
                    Keys.CONTENT_SOURCES: 1,
                    Keys.CREATED_AT: 1,
                    Keys.UPDATED_AT: 1,
                    "message_count": {"$size": f"${Keys.MESSAGES}"},
                }
            },
        ]
        return await self.collection.aggregate(pipeline).to_list(length=None)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages."""
        deleted = await self.delete_one({Keys.SESSION_ID: session_id})
        if deleted:
            logger.info(f"Deleted RAG session: {session_id}")
        return deleted

    async def get_conversation_history(
        self,
        session_id: str,
        max_messages: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get the most recent messages for a session (for LLM context).

        Args:
            session_id: Session ID
            max_messages: Maximum number of messages to return

        Returns:
            List of message dicts, most recent last
        """
        session = await self.get_session(session_id)
        if not session:
            return []

        messages = session.get(Keys.MESSAGES, [])
        return messages[-max_messages:]
