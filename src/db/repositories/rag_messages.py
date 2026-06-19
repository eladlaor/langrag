"""
RAG Messages Repository

One document per conversation turn in the ``rag_messages`` collection. This is
the split-out replacement for the unbounded embedded ``rag_conversations.messages``
array: a long-lived session can accumulate any *count* of messages (cheap) without
ever growing a single document toward the 16MB BSON limit (fatal).

Integrity contract (Mongo has no FK enforcement, so it is explicit):
- Unique ``message_id`` index prevents duplicate inserts.
- Messages are only ever queried by ``session_id``; the session document is
  owner-scoped, so cross-tenant reads stay impossible. No unscoped message
  query is exposed here.
- Cascade delete and atomic create/delete are orchestrated by
  ``ConversationsRepository`` using multi-document transactions; the
  transaction-aware methods below accept an optional Motor ``session``.
"""

import logging
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.client_session import AsyncClientSession

from constants import COLLECTION_RAG_MESSAGES
from custom_types.field_keys import RAGMessageKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class RAGMessagesRepository(BaseRepository):
    """Repository for individual RAG conversation messages."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_MESSAGES)

    async def insert_message(
        self,
        session_id: str,
        message: dict[str, Any],
        mongo_session: AsyncClientSession | None = None,
    ) -> str:
        """Insert a single message for a session.

        Args:
            session_id: Session this message belongs to (FK → rag_conversations).
            message: Message dict (message_id, role, content, citations, ...).
                ``session_id`` is stamped onto the document, overriding any value
                already present so the stored row is always self-consistent.
            mongo_session: Optional Motor client session to run inside a transaction.

        Returns:
            The message_id of the inserted document.
        """
        try:
            document = {**message, Keys.SESSION_ID: session_id}
            await self.collection.insert_one(document, session=mongo_session)
            return document[Keys.MESSAGE_ID]
        except Exception as e:
            logger.error(
                "Failed to insert rag message",
                extra={"session_id": session_id, "message_id": message.get(Keys.MESSAGE_ID), "error": str(e)},
            )
            raise

    async def get_recent(self, session_id: str, max_messages: int) -> list[dict[str, Any]]:
        """Return the most recent ``max_messages`` for a session, chronological order.

        Fetches newest-first using the (session_id, created_at DESC) index, limits
        to N, then reverses so the return order is "most recent last" — preserving
        the contract of the old embedded ``messages[-N:]`` slice.
        """
        try:
            cursor = (
                self.collection.find({Keys.SESSION_ID: session_id}, {"_id": 0})
                .sort(Keys.CREATED_AT, -1)
                .limit(max_messages)
            )
            newest_first = await cursor.to_list(max_messages)
            newest_first.reverse()
            return newest_first
        except Exception as e:
            logger.error(
                "Failed to get recent rag messages",
                extra={"session_id": session_id, "max_messages": max_messages, "error": str(e)},
            )
            raise

    async def count_for_session(self, session_id: str) -> int:
        """Count messages for a session without loading their bodies."""
        try:
            return await self.collection.count_documents({Keys.SESSION_ID: session_id})
        except Exception as e:
            logger.error(
                "Failed to count rag messages for session",
                extra={"session_id": session_id, "error": str(e)},
            )
            raise

    async def delete_for_session(
        self,
        session_id: str,
        mongo_session: AsyncClientSession | None = None,
    ) -> int:
        """Delete all messages for a session (cascade on session delete).

        Args:
            session_id: Session whose messages should be removed.
            mongo_session: Optional Motor client session to run inside a transaction.

        Returns:
            Number of deleted message documents.
        """
        try:
            result = await self.collection.delete_many(
                {Keys.SESSION_ID: session_id}, session=mongo_session
            )
            return result.deleted_count
        except Exception as e:
            logger.error(
                "Failed to delete rag messages for session",
                extra={"session_id": session_id, "error": str(e)},
            )
            raise
