"""
Sender Map Repository

Persists sender anonymization maps to MongoDB for cross-run consistency.
Ensures that user_1 always refers to the same real sender across pipeline runs,
even when the date range changes.

Key: (data_source_name, chat_name) — one sender map per chat.
"""

import logging
from datetime import datetime, UTC

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_SENDER_MAPS
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)


class SenderMapRepository(BaseRepository):
    """
    Repository for persisting sender anonymization maps across pipeline runs.

    Each chat has one sender map that maps real sender IDs to anonymized IDs
    (e.g., "@alice:beeper.com" -> "user_1"). This map grows monotonically —
    new senders are appended, existing mappings never change.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_SENDER_MAPS)

    async def get_sender_map(
        self, data_source_name: str, chat_name: str
    ) -> dict[str, str] | None:
        """
        Retrieve the persisted sender map for a chat.

        Args:
            data_source_name: Data source identifier (e.g., "langtalks")
            chat_name: Chat name (e.g., "AI Transformation Guild")

        Returns:
            Dict mapping real sender IDs to anonymized IDs, or None if not found.
        """
        try:
            doc = await self.find_one({
                DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                DbFieldKeys.CHAT_NAME: chat_name,
            })

            if not doc:
                logger.debug(f"No persisted sender map for {data_source_name}/{chat_name}")
                return None

            sender_map = doc.get("sender_map", {})
            logger.info(
                f"Loaded persisted sender map for {data_source_name}/{chat_name}: "
                f"{len(sender_map)} sender mappings"
            )
            return sender_map

        except Exception as e:
            logger.error(f"Failed to load sender map for {data_source_name}/{chat_name}: {e}")
            raise

    async def upsert_sender_map(
        self, data_source_name: str, chat_name: str, sender_map: dict[str, str]
    ) -> bool:
        """
        Persist or update the sender map for a chat.

        Args:
            data_source_name: Data source identifier
            chat_name: Chat name
            sender_map: Dict mapping real sender IDs to anonymized IDs

        Returns:
            True if the document was created or updated.
        """
        try:
            now = datetime.now(UTC)
            result = await self.update_one(
                query={
                    DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                    DbFieldKeys.CHAT_NAME: chat_name,
                },
                update={
                    "$set": {
                        DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                        DbFieldKeys.CHAT_NAME: chat_name,
                        "sender_map": sender_map,
                        "sender_count": len(sender_map),
                        DbFieldKeys.UPDATED_AT: now,
                    },
                    "$setOnInsert": {
                        DbFieldKeys.CREATED_AT: now,
                    },
                },
                upsert=True,
            )

            logger.info(
                f"Persisted sender map for {data_source_name}/{chat_name}: "
                f"{len(sender_map)} sender mappings"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to persist sender map for {data_source_name}/{chat_name}: {e}")
            raise
