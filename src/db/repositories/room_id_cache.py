"""
Room ID Cache Repository

Caches WhatsApp chat name -> Matrix room ID mappings to avoid expensive room searches.
Eliminates 3-6 minute room search (1903 rooms) by providing O(1) lookups.
"""

import logging
import re
from datetime import datetime, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from custom_types.field_keys import DbFieldKeys
from constants import COLLECTION_ROOM_ID_CACHE

logger = logging.getLogger(__name__)


class RoomIdCacheRepository(BaseRepository):
    """
    Repository for caching chat name to room ID mappings.

    Stores:
    - Chat name (primary key)
    - Matrix room ID
    - Normalized name (case-insensitive matching)
    - Access tracking (count, last accessed)

    Performance:
    - Cache hit: 1-3ms (MongoDB indexed lookup)
    - Cache miss: 3-6 minutes (searches 1903 rooms via Matrix API)
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_ROOM_ID_CACHE)

    async def get_room_id(self, chat_name: str) -> str | None:
        """
        Get room ID for a chat name.

        Args:
            chat_name: Exact chat name (case-sensitive)

        Returns:
            Room ID or None if not cached
        """
        try:
            cached = await self.find_one({DbFieldKeys.CHAT_NAME: chat_name})

            if not cached:
                logger.debug(f"Room ID cache miss: {chat_name}")
                return None

            room_id = cached.get(DbFieldKeys.ROOM_ID)

            # Update access tracking (fire-and-forget)
            await self.update_one({DbFieldKeys.CHAT_NAME: chat_name}, {"$set": {"last_accessed_at": datetime.now(UTC)}, "$inc": {"access_count": 1}})

            logger.info(f"Room ID cache hit: {chat_name} -> {room_id}")
            return room_id

        except Exception as e:
            logger.error(f"Failed to get room ID for {chat_name}: {e}")
            raise

    async def upsert_room_mapping(self, chat_name: str, room_id: str) -> str:
        """
        Create or update room ID mapping.

        Args:
            chat_name: Chat name (case-sensitive)
            room_id: Matrix room ID

        Returns:
            Chat name (primary key)
        """
        try:
            normalized_name = re.sub(r"[^a-z0-9]+", "_", chat_name.lower()).strip("_")
            now = datetime.now(UTC)

            await self.update_one(
                {DbFieldKeys.CHAT_NAME: chat_name},
                {
                    "$set": {
                        DbFieldKeys.ROOM_ID: room_id,
                        "normalized_name": normalized_name,
                        DbFieldKeys.UPDATED_AT: now,
                    },
                    "$setOnInsert": {
                        DbFieldKeys.CHAT_NAME: chat_name,
                        DbFieldKeys.CREATED_AT: now,
                        "access_count": 0,
                        "last_accessed_at": now,
                    },
                },
                upsert=True,
            )
            logger.info(f"Upserted room ID cache: {chat_name} -> {room_id}")

            return chat_name

        except Exception as e:
            logger.error(f"Failed to upsert room mapping for {chat_name}: {e}")
            raise

    async def get_all_mappings(self) -> list[dict[str, Any]]:
        """
        Get all cached room mappings.

        Returns:
            List of cache documents
        """
        try:
            return await self.find_many({}, sort=[("chat_name", 1)])
        except Exception as e:
            logger.error(f"Failed to get all room mappings: {e}")
            raise

    async def delete_mapping(self, chat_name: str) -> bool:
        """
        Delete a room ID mapping.

        Args:
            chat_name: Chat name to remove

        Returns:
            True if deleted
        """
        try:
            deleted = await self.delete_one({DbFieldKeys.CHAT_NAME: chat_name})

            if deleted:
                logger.info(f"Deleted room ID cache entry: {chat_name}")
            else:
                logger.debug(f"Room ID cache entry not found: {chat_name}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete room mapping for {chat_name}: {e}")
            raise

    async def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with stats
        """
        try:
            total_entries = await self.count()

            # Get most accessed
            pipeline = [{"$sort": {"access_count": -1}}, {"$limit": 5}, {"$project": {"chat_name": 1, "access_count": 1, "last_accessed_at": 1}}]

            top_accessed = await self.collection.aggregate(pipeline).to_list(length=None)

            stats = {"total_entries": total_entries, "top_accessed": top_accessed}

            logger.debug(f"Room ID cache stats: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            raise
