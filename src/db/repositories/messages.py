"""
Messages Repository

Manages raw message records extracted from WhatsApp chats.
"""

import logging
from datetime import datetime, UTC
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_MESSAGES
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)


class MessagesRepository(BaseRepository):
    """
    Repository for raw message storage.

    Stores:
    - Message content (original and translated)
    - Sender information
    - Timestamps
    - Reply relationships
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_MESSAGES)

    async def create_message(
        self,
        message_id: str,
        discussion_id: str,
        chat_name: str,
        sender: str,
        content: str,
        timestamp: int,
        translated_content: str = None,
        replies_to: str = None,
        metadata: dict[str, Any] = None,
    ) -> str:
        """
        Create a new message record.

        Args:
            message_id: Unique identifier (Matrix event ID)
            discussion_id: Associated discussion ID
            chat_name: Source chat name
            sender: Sender identifier
            content: Original message content
            timestamp: Message timestamp (milliseconds)
            translated_content: Translated content if available
            replies_to: ID of message this replies to
            metadata: Additional metadata

        Returns:
            Inserted document ID
        """
        document = {
            DbFieldKeys.MESSAGE_ID: message_id,
            DbFieldKeys.DISCUSSION_ID: discussion_id,
            DbFieldKeys.CHAT_NAME: chat_name,
            DbFieldKeys.SENDER: sender,
            DbFieldKeys.CONTENT: content,
            DbFieldKeys.TIMESTAMP: timestamp,
            DbFieldKeys.TRANSLATED_CONTENT: translated_content,
            DbFieldKeys.REPLIES_TO: replies_to,
            DbFieldKeys.METADATA: metadata or {},
            DbFieldKeys.CREATED_AT: datetime.now(UTC),
        }
        return await self.create(document)

    async def create_messages_bulk(
        self,
        messages: list[dict[str, Any]],
    ) -> list[str]:
        """Bulk insert messages."""
        for msg in messages:
            msg["created_at"] = datetime.now(UTC)
        return await self.create_many(messages)

    async def upsert_batch(self, messages: list[dict[str, Any]], key_field: str = "message_id") -> int:
        """
        Upsert multiple messages in one bulk operation.

        Uses bulk_write with UpdateOne(upsert=True) to insert new documents
        or update existing ones matched by key_field.

        Args:
            messages: List of message documents
            key_field: Field to match existing documents on (default: "message_id")

        Returns:
            Number of messages successfully upserted
        """
        if not messages:
            return 0

        try:
            from datetime import datetime
            from pymongo import UpdateOne

            operations = []
            now = datetime.now(UTC)
            for doc in messages:
                doc.setdefault("created_at", now)
                doc["updated_at"] = now
                operations.append(
                    UpdateOne(
                        {key_field: doc[key_field]},
                        {"$set": doc},
                        upsert=True,
                    )
                )

            result = await self.collection.bulk_write(operations, ordered=False)
            total = result.upserted_count + result.modified_count
            logger.info(f"Upserted {total} messages (inserted={result.upserted_count}, updated={result.modified_count})")
            return total
        except Exception as e:
            logger.error(f"Failed to upsert messages batch: {e}")
            return 0

    async def insert_batch(self, messages: list[dict[str, Any]]) -> int:
        """
        Insert multiple messages in one bulk operation.
        Designed for workflow integration - accepts preprocessed message format.

        Args:
            messages: List of message documents

        Returns:
            Number of messages successfully inserted
        """
        if not messages:
            return 0

        try:
            # Add created_at if not present
            for msg in messages:
                if "created_at" not in msg:
                    msg["created_at"] = datetime.now(UTC)

            # Use ordered=False to continue inserting even if some fail (e.g., duplicates)
            result = await self.collection.insert_many(messages, ordered=False)
            return len(result.inserted_ids)
        except Exception as e:
            logger.error(f"Failed to insert messages batch: {e}")
            return 0

    async def get_messages_by_run(self, run_id: str, chat_name: str | None = None, limit: int = 10000) -> list[dict[str, Any]]:
        """
        Get messages for a run, optionally filtered by chat.

        Args:
            run_id: Run identifier
            chat_name: Optional chat name filter
            limit: Maximum messages to return

        Returns:
            List of message documents sorted by timestamp
        """
        query = {"run_id": run_id}
        if chat_name:
            query[DbFieldKeys.CHAT_NAME] = chat_name

        return await self.find_many(query, sort=[("timestamp", 1)], limit=limit)

    async def count_messages_by_run(self, run_id: str, chat_name: str | None = None) -> int:
        """
        Count messages for a run.

        Args:
            run_id: Run identifier
            chat_name: Optional chat filter

        Returns:
            Message count
        """
        query = {"run_id": run_id}
        if chat_name:
            query[DbFieldKeys.CHAT_NAME] = chat_name

        return await self.count(query)

    async def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a message by its ID."""
        return await self.find_by_id(DbFieldKeys.MESSAGE_ID, message_id)

    async def get_messages_by_discussion(
        self,
        discussion_id: str,
    ) -> list[dict[str, Any]]:
        """Get all messages in a discussion, sorted by timestamp."""
        return await self.find_many(
            {DbFieldKeys.DISCUSSION_ID: discussion_id},
            sort=[("timestamp", 1)],
        )

    async def get_messages_by_chat_and_range(
        self,
        chat_name: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[dict[str, Any]]:
        """Get messages from a chat within a time range."""
        return await self.find_many(
            {
                "chat_name": chat_name,
                "timestamp": {"$gte": start_timestamp, "$lte": end_timestamp},
            },
            sort=[("timestamp", 1)],
        )

    async def get_message_thread(
        self,
        message_id: str,
    ) -> list[dict[str, Any]]:
        """Get a message and all its replies (thread)."""
        # Get the root message
        root = await self.get_message(message_id)
        if not root:
            return []

        # Get all replies
        replies = await self.find_many(
            {"replies_to": message_id},
            sort=[("timestamp", 1)],
        )

        return [root] + replies
