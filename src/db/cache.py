"""
MongoDB Cache

Caches expensive LLM operations using MongoDB with TTL-based expiration.
Fail-soft: cache failures don't break the application.

Usage (async - LangGraph 1.0+ nodes):
    from db.cache import _get_cache

    cache = _get_cache()
    cached = await cache.get("translate", input_hash)
    if not cached:
        result = expensive_llm_call(input)
        await cache.set("translate", input_hash, result)
"""

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 7


class CacheService:
    """MongoDB-backed cache for LLM operations."""

    def __init__(self, ttl_days: int = DEFAULT_TTL_DAYS):
        self._ttl_days = ttl_days
        self._db = None
        self._cache_repo = None
        self._initialized = False

    async def _ensure_initialized(self) -> bool:
        """Lazily initialize MongoDB connection."""
        if self._initialized:
            return True

        try:
            from db.connection import get_database
            from db.repositories.cache import CacheRepository

            self._db = await get_database()
            self._cache_repo = CacheRepository(self._db)
            self._initialized = True
            return True
        except Exception as e:
            logger.debug(f"MongoDB cache not available: {e}")
            return False

    @staticmethod
    def generate_hash(content: str) -> str:
        """Generate SHA256 hash for cache key."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def get(self, operation: str, content_hash: str) -> Any | None:
        """Get cached value."""
        if not await self._ensure_initialized():
            return None

        try:
            cache_key = f"{operation}:{content_hash}"
            cached = await self._cache_repo.get_cached(cache_key)
            if cached and cached.get("value"):
                logger.debug(f"Cache hit: {operation}")
                return cached["value"]
            return None
        except Exception as e:
            logger.debug(f"Cache get failed: {e}")
            return None

    async def set(self, operation: str, content_hash: str, value: Any, metadata: dict | None = None) -> bool:
        """Store value in cache."""
        if not await self._ensure_initialized():
            return False

        try:
            cache_key = f"{operation}:{content_hash}"
            ttl_seconds = self._ttl_days * 24 * 60 * 60
            await self._cache_repo.set_cached(key=cache_key, value=value, operation=operation, ttl_seconds=ttl_seconds, metadata=metadata)
            return True
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")
            return False

    async def invalidate(self, operation: str, content_hash: str) -> bool:
        """Invalidate a cache entry."""
        if not await self._ensure_initialized():
            return False

        try:
            cache_key = f"{operation}:{content_hash}"
            await self._cache_repo.invalidate(cache_key)
            return True
        except Exception as e:
            logger.debug(f"Cache invalidate failed: {e}")
            return False

    async def invalidate_operation(self, operation: str) -> int:
        """Invalidate all entries for an operation."""
        if not await self._ensure_initialized():
            return 0

        try:
            return await self._cache_repo.invalidate_by_operation(operation)
        except Exception as e:
            logger.debug(f"Cache invalidate_operation failed: {e}")
            return 0

    async def get_stats(self) -> dict:
        """Get cache statistics."""
        if not await self._ensure_initialized():
            return {"error": "Cache not available"}

        try:
            return await self._cache_repo.get_cache_stats()
        except Exception as e:
            return {"error": str(e)}


# Singleton
_cache: CacheService | None = None


def _get_cache() -> CacheService:
    """Get the singleton CacheService instance for use in async nodes."""
    global _cache
    if _cache is None:
        _cache = CacheService()
    return _cache
