"""
RAG Conversation Manager

Session lifecycle management: create, retrieve, append messages, delete.
Acts as a thin coordination layer between the API and the repository.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from config import get_settings
from constants import MessageRole
from custom_types.field_keys import RAGConversationKeys as Keys
from db.connection import get_database
from db.repositories.rag_conversations import ConversationsRepository
from rag.generation.rag_chain import generate_session_title

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Manages RAG conversation sessions.

    Responsibilities:
    - Session CRUD
    - Message persistence (user + assistant messages with citations)
    - Conversation history retrieval for LLM context
    - Auto-title generation from first query
    """

    async def create_session(
        self,
        content_sources: list[str],
        title: str | None = None,
    ) -> str:
        """
        Create a new conversation session.

        Args:
            content_sources: Content source types to search
            title: Optional title (auto-generated from first query if None)

        Returns:
            New session_id (UUID)
        """
        repo = await self._get_repo()
        session_id = str(uuid.uuid4())
        await repo.create_session(session_id, content_sources, title)
        return session_id

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a session with full message history."""
        repo = await self._get_repo()
        return await repo.get_session(session_id)

    async def list_sessions(self, limit: int = 20, skip: int = 0) -> list[dict[str, Any]]:
        """List sessions (metadata only, no full history)."""
        repo = await self._get_repo()
        return await repo.list_sessions(limit=limit, skip=skip)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        repo = await self._get_repo()
        return await repo.delete_session(session_id)

    async def add_user_message(self, session_id: str, content: str) -> str:
        """
        Record a user message in the session.

        Args:
            session_id: Session ID
            content: User message text

        Returns:
            message_id (UUID)
        """
        repo = await self._get_repo()
        message_id = str(uuid.uuid4())
        message = {
            Keys.MESSAGE_ID: message_id,
            Keys.ROLE: str(MessageRole.USER),
            Keys.CONTENT: content,
            Keys.CREATED_AT: datetime.now(timezone.utc),
        }
        await repo.append_message(session_id, message)

        # Auto-generate title from first query
        session = await repo.get_session(session_id)
        if session and not session.get(Keys.TITLE) and len(session.get(Keys.MESSAGES, [])) <= 1:
            try:
                title = await generate_session_title(content)
                await repo.update_title(session_id, title)
            except Exception as e:
                logger.warning(f"Failed to auto-generate session title: {e}")

        return message_id

    async def add_assistant_message(
        self,
        session_id: str,
        content: str,
        citations: list[dict] | None = None,
        evaluation_id: str | None = None,
    ) -> str:
        """
        Record an assistant message with citations.

        Args:
            session_id: Session ID
            content: Assistant response text
            citations: Citation metadata list
            evaluation_id: Optional evaluation ID (if DeepEval is enabled)

        Returns:
            message_id (UUID)
        """
        repo = await self._get_repo()
        message_id = str(uuid.uuid4())
        message = {
            Keys.MESSAGE_ID: message_id,
            Keys.ROLE: str(MessageRole.ASSISTANT),
            Keys.CONTENT: content,
            Keys.CITATIONS: citations or [],
            Keys.EVALUATION_ID: evaluation_id,
            Keys.CREATED_AT: datetime.now(timezone.utc),
        }
        await repo.append_message(session_id, message)
        return message_id

    async def get_conversation_history(
        self,
        session_id: str,
        max_messages: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent conversation history for LLM context.

        Args:
            session_id: Session ID
            max_messages: Override max messages (default from config)

        Returns:
            List of message dicts (role, content), most recent last
        """
        limit = max_messages or get_settings().rag.max_conversation_history
        repo = await self._get_repo()
        return await repo.get_conversation_history(session_id, max_messages=limit)

    @staticmethod
    async def _get_repo() -> ConversationsRepository:
        db = await get_database()
        return ConversationsRepository(db)
