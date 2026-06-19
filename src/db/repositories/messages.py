"""
Messages Repository

Manages raw message records extracted from WhatsApp chats.
"""

import logging
from datetime import datetime, UTC
from typing import Any
from pymongo.asynchronous.database import AsyncDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_MESSAGES, CURRENT_SCHEMA_VERSION_MESSAGE, DEFAULT_MESSAGES_QUERY_LIMIT, SCHEMA_VERSION_FIELD
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)

# MongoDB server error code for a duplicate-key violation.
_DUPLICATE_KEY_ERROR_CODE = 11000

# Reusable chronological sort key for message queries.
_SORT_BY_TIMESTAMP_ASC = [(DbFieldKeys.TIMESTAMP, 1)]


class MessagesRepository(BaseRepository):
    """
    Repository for raw message storage.

    Stores:
    - Message content (original and translated)
    - Sender information
    - Timestamps
    - Reply relationships
    """

    def __init__(self, db: AsyncDatabase):
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
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_MESSAGE,
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
            msg[DbFieldKeys.CREATED_AT] = datetime.now(UTC)
            msg.setdefault(SCHEMA_VERSION_FIELD, CURRENT_SCHEMA_VERSION_MESSAGE)
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

        from pymongo import UpdateOne
        from pymongo.errors import BulkWriteError

        operations = []
        now = datetime.now(UTC)
        for doc in messages:
            # created_at and schema_version are insert-only: a re-ingest of an
            # existing message (the translated pass) must NOT reset them. Pull
            # them out of $set and into $setOnInsert.
            set_fields = {k: v for k, v in doc.items() if k not in (DbFieldKeys.CREATED_AT, SCHEMA_VERSION_FIELD)}
            set_fields[DbFieldKeys.UPDATED_AT] = now
            on_insert = {
                DbFieldKeys.CREATED_AT: doc.get(DbFieldKeys.CREATED_AT, now),
                SCHEMA_VERSION_FIELD: doc.get(SCHEMA_VERSION_FIELD, CURRENT_SCHEMA_VERSION_MESSAGE),
            }
            operations.append(
                UpdateOne(
                    {key_field: doc[key_field]},
                    {"$set": set_fields, "$setOnInsert": on_insert},
                    upsert=True,
                )
            )

        # Fail-fast: a partial/total write failure must propagate (with the
        # per-op error details) rather than be masked as "0 upserted", which is
        # indistinguishable from empty input and silently loses data.
        try:
            result = await self.collection.bulk_write(operations, ordered=False)
        except BulkWriteError as e:
            logger.error(f"Bulk upsert of {len(operations)} messages failed: {e.details}")
            raise
        total = result.upserted_count + result.modified_count
        logger.info(f"Upserted {total} messages (inserted={result.upserted_count}, updated={result.modified_count})")
        return total

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

        from pymongo.errors import BulkWriteError

        # Add created_at if not present
        for msg in messages:
            if DbFieldKeys.CREATED_AT not in msg:
                msg[DbFieldKeys.CREATED_AT] = datetime.now(UTC)
            msg.setdefault(SCHEMA_VERSION_FIELD, CURRENT_SCHEMA_VERSION_MESSAGE)

        # Use ordered=False to continue inserting even if some fail.
        try:
            result = await self.collection.insert_many(messages, ordered=False)
            return len(result.inserted_ids)
        except BulkWriteError as e:
            # Duplicate keys (code 11000) are benign on re-ingest: the document
            # already exists, so treat those as "already stored" and report the
            # count that DID insert. ANY other write error is real data loss and
            # must propagate (fail-fast).
            write_errors = e.details.get("writeErrors", [])
            non_duplicate = [we for we in write_errors if we.get("code") != _DUPLICATE_KEY_ERROR_CODE]
            if non_duplicate:
                logger.error(f"Bulk insert of {len(messages)} messages hit non-duplicate errors: {non_duplicate}")
                raise
            inserted = e.details.get("nInserted", 0)
            logger.info(f"Inserted {inserted}/{len(messages)} messages ({len(write_errors)} pre-existing, skipped)")
            return inserted

    async def get_messages_by_run(self, run_id: str, chat_name: str | None = None, limit: int = DEFAULT_MESSAGES_QUERY_LIMIT) -> list[dict[str, Any]]:
        """
        Get messages for a run, optionally filtered by chat.

        The default limit is intentionally bounded (DEFAULT_MESSAGES_QUERY_LIMIT)
        so the convenience path cannot silently materialize a whole busy run into
        memory. To retrieve an unbounded run, page through get_messages_page
        (keyset pagination) rather than raising this limit.

        Args:
            run_id: Run identifier
            chat_name: Optional chat name filter
            limit: Maximum messages to return

        Returns:
            List of message documents sorted by timestamp
        """
        query = {DbFieldKeys.RUN_ID: run_id}
        if chat_name:
            query[DbFieldKeys.CHAT_NAME] = chat_name

        return await self.find_many(query, sort=_SORT_BY_TIMESTAMP_ASC, limit=limit)

    async def get_messages_page(
        self,
        run_id: str,
        chat_name: str | None = None,
        page_size: int = 1000,
        cursor: tuple[int, str] | None = None,
    ) -> tuple[list[dict[str, Any]], tuple[int, str] | None]:
        """
        Range-based (keyset) pagination over a run's messages.

        Unlike skip/limit, this scans forward from a stable (timestamp,
        message_id) cursor, so it stays O(page_size) regardless of how deep the
        page is and is immune to documents shifting between pages. Backed by the
        {run_id, chat_name, timestamp} compound index; the find_many ceiling is
        now only a backstop, not the paging mechanism.

        Args:
            run_id: Run identifier (equality).
            chat_name: Optional chat-name filter (equality).
            page_size: Max documents per page.
            cursor: (timestamp, message_id) of the last doc from the previous
                page, or None for the first page.

        Returns:
            (page, next_cursor). next_cursor is None when the run is exhausted.
        """
        query: dict[str, Any] = {DbFieldKeys.RUN_ID: run_id}
        if chat_name:
            query[DbFieldKeys.CHAT_NAME] = chat_name
        if cursor is not None:
            last_ts, last_id = cursor
            # Strictly after the cursor in (timestamp, message_id) order. The
            # message_id tiebreaker keeps progress correct when timestamps tie.
            query["$or"] = [
                {DbFieldKeys.TIMESTAMP: {"$gt": last_ts}},
                {DbFieldKeys.TIMESTAMP: last_ts, DbFieldKeys.MESSAGE_ID: {"$gt": last_id}},
            ]

        page = await self.find_many(
            query,
            sort=[(DbFieldKeys.TIMESTAMP, 1), (DbFieldKeys.MESSAGE_ID, 1)],
            limit=page_size,
        )

        next_cursor: tuple[int, str] | None = None
        if len(page) == page_size:
            last = page[-1]
            next_cursor = (last[DbFieldKeys.TIMESTAMP], last[DbFieldKeys.MESSAGE_ID])
        return page, next_cursor

    async def count_messages_by_run(self, run_id: str, chat_name: str | None = None) -> int:
        """
        Count messages for a run.

        Args:
            run_id: Run identifier
            chat_name: Optional chat filter

        Returns:
            Message count
        """
        query = {DbFieldKeys.RUN_ID: run_id}
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
            sort=_SORT_BY_TIMESTAMP_ASC,
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
                DbFieldKeys.CHAT_NAME: chat_name,
                DbFieldKeys.TIMESTAMP: {"$gte": start_timestamp, "$lte": end_timestamp},
            },
            sort=_SORT_BY_TIMESTAMP_ASC,
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
            {DbFieldKeys.REPLIES_TO: message_id},
            sort=_SORT_BY_TIMESTAMP_ASC,
        )

        return [root] + replies
