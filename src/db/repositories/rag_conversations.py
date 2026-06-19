"""
RAG Conversations Repository

CRUD operations for the rag_conversations collection (chat session metadata).

Message history is NOT embedded here. Each turn lives as its own document in the
``rag_messages`` collection (see RAGMessagesRepository), referenced by
``session_id``. This split removes the only real 16MB BSON document-size risk in
the codebase: a long-lived session grows in message *count* (cheap), not in
document *size* (fatal). The session document holds metadata only.

This repository owns cross-collection integrity:
- ``append_message`` inserts into rag_messages and bumps ``updated_at`` atomically.
- ``delete_session`` cascades a delete_many over rag_messages atomically.

The public method signatures are unchanged from the embedded-array era so callers
(ConversationManager, the API layer) need no changes beyond the first-message
title check, which now counts rag_messages instead of measuring an array length.
"""

import logging
from datetime import datetime, UTC
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from constants import COLLECTION_RAG_CONVERSATIONS
from custom_types.field_keys import RAGConversationKeys as Keys
from db.connection import get_client
from db.repositories.base import BaseRepository
from db.repositories.rag_messages import RAGMessagesRepository

logger = logging.getLogger(__name__)


class ConversationsRepository(BaseRepository):
    """Repository for RAG conversation sessions (metadata; messages live in rag_messages)."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_CONVERSATIONS)
        self._messages = RAGMessagesRepository(db)

    async def create_session(
        self,
        session_id: str,
        content_sources: list[str],
        owner: str,
        title: str | None = None,
    ) -> str:
        """
        Create a new conversation session.

        Args:
            session_id: UUID for the session
            content_sources: List of content source types to search
            owner: Identity (API-key owner) that owns this session. Used to scope
                all subsequent reads/deletes so callers cannot access others' sessions.
            title: Optional session title (auto-generated from first query if None)

        Returns:
            session_id
        """
        now = datetime.now(UTC)
        document = {
            Keys.SESSION_ID: session_id,
            Keys.OWNER: owner,
            Keys.TITLE: title,
            Keys.CONTENT_SOURCES: content_sources,
            Keys.CREATED_AT: now,
            Keys.UPDATED_AT: now,
        }
        await self.create(document)
        logger.info(f"Created RAG session: {session_id}")
        return session_id

    async def get_session(
        self,
        session_id: str,
        owner: str | None = None,
        include_messages: bool = False,
    ) -> dict[str, Any] | None:
        """Get a session by ID, optionally scoped to its owner.

        When ``owner`` is provided, a session created by a different owner returns
        None (no cross-owner reads). When ``owner`` is None the lookup is unscoped —
        reserved for internal callers that have already authorized access.

        When ``include_messages`` is True, the session's full message history is
        hydrated from ``rag_messages`` and attached under the ``messages`` key, so
        the public read shape matches the old embedded-array contract. The default
        is False because the hot paths (existence checks before generating a turn)
        do not read history — they call ``get_conversation_history`` separately.
        """
        if owner is None:
            session = await self.find_by_id(Keys.SESSION_ID, session_id)
        else:
            session = await self.find_one({Keys.SESSION_ID: session_id, Keys.OWNER: owner})

        if session is not None and include_messages:
            session[Keys.MESSAGES] = await self._messages.get_recent(
                session_id, max_messages=_ALL_MESSAGES_LIMIT
            )
        return session

    async def append_message(
        self,
        session_id: str,
        message: dict[str, Any],
    ) -> bool:
        """
        Append a message to a session's history.

        Inserts the message as its own document in ``rag_messages`` and bumps the
        session's ``updated_at`` in the same multi-document transaction, so a reader
        never sees a session whose ``updated_at`` moved without the message landing
        (or vice versa). The transaction does NOT span the LLM call — it wraps only
        the two writes.

        Args:
            session_id: Session to update
            message: Message dict with message_id, role, content, citations, etc.

        Returns:
            True (the insert is the source of truth; raises on failure — fail-fast).
        """
        client = await get_client()
        try:
            async with await client.start_session() as mongo_session:
                async with mongo_session.start_transaction():
                    await self._messages.insert_message(session_id, message, mongo_session=mongo_session)
                    await self.collection.update_one(
                        {Keys.SESSION_ID: session_id},
                        {"$set": {Keys.UPDATED_AT: datetime.now(UTC)}},
                        session=mongo_session,
                    )
            return True
        except Exception as e:
            logger.error(
                "Failed to append rag message (transaction rolled back)",
                extra={"session_id": session_id, "message_id": message.get(Keys.MESSAGE_ID), "error": str(e)},
            )
            raise

    async def update_title(self, session_id: str, title: str) -> bool:
        """Set or update session title (typically auto-generated from first query)."""
        return await self.update_one(
            {Keys.SESSION_ID: session_id},
            {"$set": {Keys.TITLE: title, Keys.UPDATED_AT: datetime.now(UTC)}},
        )

    async def list_sessions(
        self,
        owner: str,
        limit: int = 20,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List the given owner's sessions ordered by most recently updated.

        Returns session metadata plus a ``message_count`` (queried per session from
        ``rag_messages`` via a counted index lookup — no message bodies are loaded).
        Results are scoped to ``owner`` so callers never see others' sessions.
        """
        sessions = await self.find_many(
            {Keys.OWNER: owner},
            sort=[(Keys.UPDATED_AT, -1)],
            limit=limit,
            skip=skip,
            projection={
                "_id": 0,
                Keys.SESSION_ID: 1,
                Keys.TITLE: 1,
                Keys.CONTENT_SOURCES: 1,
                Keys.CREATED_AT: 1,
                Keys.UPDATED_AT: 1,
            },
        )
        for session in sessions:
            session["message_count"] = await self._messages.count_for_session(session[Keys.SESSION_ID])
        return sessions

    async def delete_session(self, session_id: str, owner: str | None = None) -> bool:
        """Delete a session and all its messages, optionally scoped to its owner.

        The session document and its ``rag_messages`` are removed in a single
        multi-document transaction, so a failure mid-delete leaves no orphaned
        messages and no half-deleted session.

        When ``owner`` is provided, only a session owned by that identity is deleted;
        a mismatch deletes nothing and returns False (no cross-owner deletes).
        """
        query = {Keys.SESSION_ID: session_id}
        if owner is not None:
            query[Keys.OWNER] = owner

        client = await get_client()
        try:
            async with await client.start_session() as mongo_session:
                async with mongo_session.start_transaction():
                    result = await self.collection.delete_one(query, session=mongo_session)
                    deleted = result.deleted_count > 0
                    if deleted:
                        await self._messages.delete_for_session(session_id, mongo_session=mongo_session)
        except Exception as e:
            logger.error(
                "Failed to delete rag session (transaction rolled back)",
                extra={"session_id": session_id, "error": str(e)},
            )
            raise

        if deleted:
            logger.info(f"Deleted RAG session: {session_id}")
        return deleted

    async def count_messages(self, session_id: str) -> int:
        """Count messages for a session (used for the title-on-first-message check)."""
        return await self._messages.count_for_session(session_id)

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
        return await self._messages.get_recent(session_id, max_messages=max_messages)


# Sentinel "no real cap" used when hydrating the full history for a session read.
# A session's message count is bounded by usage, not by this limit; it exists only
# so get_recent has a concrete value to pass to .limit().
_ALL_MESSAGES_LIMIT = 10_000
