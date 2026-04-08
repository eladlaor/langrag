"""
Extraction Cache Repository

Caches Beeper message extraction results to avoid redundant API calls.
Uses TTL indexes for automatic cleanup of expired cache entries.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from config import get_settings
from custom_types.field_keys import DbFieldKeys
from constants import COLLECTION_EXTRACTION_CACHE

logger = logging.getLogger(__name__)


class ExtractionCacheRepository(BaseRepository):
    """
    Repository for caching Beeper extraction results.

    Stores:
    - Extracted messages from Beeper API
    - Extraction metadata (timestamp, decryption method, keys used)
    - Automatic TTL-based expiration

    Cache Key Format:
        "beeper_{chat_name}_{start_date}_{end_date}"
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_EXTRACTION_CACHE)
        self._settings = get_settings()

    async def get_cached_extraction(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached extraction by cache key.

        Args:
            cache_key: Unique cache identifier (e.g., "beeper_langtalks_community_2025-10-01_2025-10-14")

        Returns:
            Cached extraction document or None if not found/expired
        """
        try:
            cached = await self.find_one({"cache_key": cache_key})

            if not cached:
                logger.debug(f"Cache miss: {cache_key}")
                return None

            # Check if expired (TTL index should handle this, but double-check)
            expires_at = cached.get("expires_at")
            if expires_at and isinstance(expires_at, datetime):
                # MongoDB returns offset-naive datetimes (UTC assumed), make timezone-aware
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if datetime.now(UTC) > expires_at:
                    logger.info(f"Cache expired: {cache_key}")
                    await self.invalidate_cache(cache_key)
                    return None

            message_count = cached.get("message_count", 0)
            logger.info(f"Cache hit: {cache_key} ({message_count} messages)")
            return cached

        except Exception as e:
            logger.error(f"Failed to get cached extraction for {cache_key}: {e}")
            raise

    async def set_cached_extraction(self, cache_key: str, chat_name: str, room_id: str, start_date: str, end_date: str, messages: list[dict[str, Any]], extraction_metadata: dict[str, Any] | None = None) -> str:
        """
        Store extraction results in cache.

        Args:
            cache_key: Unique cache identifier
            chat_name: Name of the chat
            room_id: Matrix room ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            messages: List of extracted message dictionaries
            extraction_metadata: Optional metadata about extraction process

        Returns:
            Inserted document ID
        """
        try:
            now = datetime.now(UTC)
            ttl_days = self._settings.database.extraction_cache_ttl_days

            # Count encrypted messages
            encrypted_count = sum(1 for msg in messages if msg.get("encrypted", False))

            document = {"cache_key": cache_key, DbFieldKeys.CHAT_NAME: chat_name, "chat_name_normalized": self._normalize_chat_name(chat_name), DbFieldKeys.ROOM_ID: room_id, "start_date": start_date, "end_date": end_date, "messages": messages, "message_count": len(messages), "encrypted_count": encrypted_count, "extraction_metadata": extraction_metadata or {}, "created_at": now, "expires_at": now + timedelta(days=ttl_days)}

            # Upsert to handle re-caching
            await self.update_one({"cache_key": cache_key}, {"$set": document}, upsert=True)

            logger.info(f"Cached extraction: {cache_key} " f"({len(messages)} messages, {encrypted_count} encrypted, TTL={ttl_days}d)")

            return cache_key

        except Exception as e:
            logger.error(f"Failed to cache extraction for {cache_key}: {e}")
            raise

    async def invalidate_cache(self, cache_key: str) -> bool:
        """
        Invalidate (delete) a specific cache entry.

        Args:
            cache_key: Cache identifier to invalidate

        Returns:
            True if cache entry was deleted
        """
        try:
            deleted = await self.delete_one({"cache_key": cache_key})

            if deleted:
                logger.info(f"Invalidated cache: {cache_key}")
            else:
                logger.debug(f"Cache entry not found for invalidation: {cache_key}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to invalidate cache {cache_key}: {e}")
            raise

    async def clear_expired_cache(self) -> int:
        """
        Manually clear all expired cache entries.

        Note: TTL index should handle this automatically, but this method
        provides manual cleanup if needed (e.g., for testing or maintenance).

        Returns:
            Number of expired entries deleted
        """
        try:
            now = datetime.now(UTC)
            deleted_count = await self.delete_many({"expires_at": {"$lt": now}})

            if deleted_count > 0:
                logger.info(f"Manually cleared {deleted_count} expired cache entries")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to clear expired cache: {e}")
            raise

    async def get_cache_stats(self) -> dict[str, Any]:
        """
        Get statistics about the extraction cache.

        Returns:
            Dictionary with cache statistics
        """
        try:
            total_entries = await self.count()

            # Count by chat name
            pipeline = [{"$group": {"_id": "$chat_name", "count": {"$sum": 1}, "total_messages": {"$sum": "$message_count"}}}, {"$sort": {"count": -1}}]

            by_chat = await self.collection.aggregate(pipeline).to_list(length=None)

            # Count expired entries
            now = datetime.now(UTC)
            expired_count = await self.count({"expires_at": {"$lt": now}})

            stats = {"total_entries": total_entries, "expired_entries": expired_count, "active_entries": total_entries - expired_count, "by_chat": by_chat}

            logger.debug(f"Cache stats: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            raise

    async def get_overlapping_extractions(
        self, chat_name: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """
        Find cached extractions whose date range overlaps with the requested range.

        Used for incremental extraction: when extending a date range (e.g., Mar 19-Apr 4
        to Mar 19-Apr 6), find existing cached extractions that cover part of the range
        and only extract the delta from the API.

        Args:
            chat_name: Name of the chat
            start_date: Requested start date (YYYY-MM-DD)
            end_date: Requested end date (YYYY-MM-DD)

        Returns:
            List of cached extraction documents with overlapping date ranges,
            sorted by start_date ascending.
        """
        try:
            normalized_name = self._normalize_chat_name(chat_name)

            # Overlap condition: cached.start <= requested.end AND cached.end >= requested.start
            docs = await self.find_many(
                query={
                    "chat_name_normalized": normalized_name,
                    "start_date": {"$lte": end_date},
                    "end_date": {"$gte": start_date},
                },
                sort=[("start_date", 1)],
            )

            if docs:
                logger.info(
                    f"Found {len(docs)} overlapping extraction cache entries for "
                    f"{chat_name} [{start_date} to {end_date}]"
                )
            else:
                logger.debug(f"No overlapping extraction cache entries for {chat_name}")

            return docs

        except Exception as e:
            logger.error(f"Failed to query overlapping extractions for {chat_name}: {e}")
            raise

    def _normalize_chat_name(self, chat_name: str) -> str:
        """Normalize chat name to lowercase with underscores for consistent lookups."""
        import re
        return re.sub(r"[^a-z0-9]+", "_", chat_name.lower()).strip("_")

    def generate_cache_key(self, chat_name: str, start_date: str, end_date: str) -> str:
        """
        Generate a cache key for a chat and date range.

        Args:
            chat_name: Name of the chat
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Cache key string
        """
        normalized_name = self._normalize_chat_name(chat_name)
        return f"beeper_{normalized_name}_{start_date}_{end_date}"
