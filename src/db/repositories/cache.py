"""
Cache Repository

Manages LLM response caching to reduce API calls and costs.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, UTC
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_CACHE

logger = logging.getLogger(__name__)


class CacheRepository(BaseRepository):
    """
    Repository for LLM response caching.

    Features:
    - Content-based cache keys (hash of input)
    - TTL-based expiration
    - Operation type categorization
    """

    DEFAULT_TTL_HOURS = 24 * 7  # 7 days

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_CACHE)

    @staticmethod
    def generate_cache_key(
        operation_type: str,
        input_data: Any,
    ) -> str:
        """
        Generate a deterministic cache key from operation type and input.

        Args:
            operation_type: Type of operation (e.g., "translate", "generate")
            input_data: Input data (will be JSON serialized)

        Returns:
            SHA256 hash as cache key
        """
        # Serialize input for hashing
        if isinstance(input_data, str):
            input_str = input_data
        else:
            input_str = json.dumps(input_data, sort_keys=True, ensure_ascii=False)

        combined = f"{operation_type}:{input_str}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def get_cached(
        self,
        cache_key: str,
    ) -> dict[str, Any] | None:
        """
        Get cached response if exists and not expired.

        Args:
            cache_key: Cache key to look up

        Returns:
            Cached response data or None
        """
        result = await self.find_one(
            {
                "cache_key": cache_key,
                "expires_at": {"$gt": datetime.now(UTC)},
            }
        )

        if result:
            logger.debug(f"Cache hit for key: {cache_key[:16]}...")
            return result.get("response_data")

        return None

    async def set_cached(
        self,
        cache_key: str,
        operation_type: str,
        input_data: Any,
        response_data: Any,
        ttl_hours: int = None,
    ) -> str:
        """
        Store a response in cache.

        Args:
            cache_key: Cache key
            operation_type: Type of operation
            input_data: Original input (for debugging)
            response_data: Response to cache
            ttl_hours: Time to live in hours (default: 7 days)

        Returns:
            Inserted document ID
        """
        ttl = ttl_hours or self.DEFAULT_TTL_HOURS
        expires_at = datetime.now(UTC) + timedelta(hours=ttl)

        document = {
            "cache_key": cache_key,
            "operation_type": operation_type,
            "input_hash": hashlib.sha256(json.dumps(input_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],  # Short hash for debugging
            "response_data": response_data,
            "created_at": datetime.now(UTC),
            "expires_at": expires_at,
        }

        # Upsert to handle duplicate keys
        await self.update_one(
            {"cache_key": cache_key},
            {"$set": document},
            upsert=True,
        )

        logger.debug(f"Cached response for key: {cache_key[:16]}...")
        return cache_key

    async def invalidate(self, cache_key: str) -> bool:
        """Invalidate a specific cache entry."""
        return await self.delete_one({"cache_key": cache_key})

    async def invalidate_by_operation(self, operation_type: str) -> int:
        """Invalidate all cache entries for an operation type."""
        return await self.delete_many({"operation_type": operation_type})

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = await self.count()
        expired = await self.count({"expires_at": {"$lt": datetime.now(UTC)}})

        # Count by operation type
        pipeline = [
            {"$group": {"_id": "$operation_type", "count": {"$sum": 1}}},
        ]
        cursor = self.collection.aggregate(pipeline)
        by_type = {doc["_id"]: doc["count"] async for doc in cursor}

        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "by_operation_type": by_type,
        }
