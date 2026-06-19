"""
Extraction Cache Repository

Caches Beeper message extraction results to avoid redundant API calls.
Uses TTL indexes for automatic cleanup of expired cache entries.

Storage layout (auto-split): the parent `extraction_cache` document holds only
metadata (cache_key, names, dates, counts, TTL). The extracted message array is
sharded across `extraction_cache_chunks` documents so a wide date range over a
busy chat can never push a single document toward the 16MB BSON ceiling. The
split is transparent to callers: read methods re-attach a fully-assembled
`messages` list onto the returned parent dict. Legacy parents that still embed an
inline `messages` array are read back directly until they TTL-expire.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from db.repositories.base import BaseRepository
from config import get_settings
from custom_types.field_keys import DbFieldKeys, DecryptionResultKeys, ExtractionCacheKeys
from constants import COLLECTION_EXTRACTION_CACHE, COLLECTION_EXTRACTION_CACHE_CHUNKS, DEFAULT_MAX_QUERY_RESULTS, EXTRACTION_CACHE_CHUNK_SIZE, MatrixEventType

logger = logging.getLogger(__name__)


class ExtractionCacheRepository(BaseRepository):
    """
    Repository for caching Beeper extraction results.

    Stores:
    - Extracted messages from Beeper API (sharded into a companion chunk collection)
    - Extraction metadata (timestamp, decryption method, keys used)
    - Automatic TTL-based expiration (parent and chunks share the same clock)

    Cache Key Format:
        "beeper_{chat_name}_{start_date}_{end_date}"
    """

    def __init__(self, db: AsyncDatabase):
        super().__init__(db, COLLECTION_EXTRACTION_CACHE)
        self._settings = get_settings()
        # Companion collection holding sharded message arrays. Accessed directly
        # (BaseRepository binds a single collection); same DB handle, default
        # write concern (cache data, not durable records).
        self._chunks = self.db[COLLECTION_EXTRACTION_CACHE_CHUNKS]

    async def get_cached_extraction(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached extraction by cache key, with messages assembled from chunks.

        Args:
            cache_key: Unique cache identifier (e.g., "beeper_langtalks_community_2025-10-01_2025-10-14")

        Returns:
            Cached extraction document (with an assembled `messages` list) or None
            if not found / expired / corrupt.
        """
        try:
            cached = await self.find_one({ExtractionCacheKeys.CACHE_KEY: cache_key})

            if not cached:
                logger.debug(f"Cache miss: {cache_key}")
                return None

            # Check if expired (TTL index should handle this, but double-check)
            expires_at = cached.get(ExtractionCacheKeys.EXPIRES_AT)
            if expires_at and isinstance(expires_at, datetime):
                # MongoDB returns offset-naive datetimes (UTC assumed), make timezone-aware
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if datetime.now(UTC) > expires_at:
                    logger.info(f"Cache expired: {cache_key}")
                    await self.invalidate_cache(cache_key)
                    return None

            assembled = await self._assemble_messages(cached)
            if assembled is None:
                # Chunk count / length mismatch. Treat as a MISS (return None)
                # rather than deleting: the mismatch is usually transient — a
                # concurrent re-cache (delete-old-chunks then insert-new, no
                # transaction) or a brief parent/chunk TTL skew. A reader that
                # deleted here could nuke another writer's in-flight entry. The
                # next writer's upsert or the TTL monitor owns deletion; we just
                # decline to serve a possibly-truncated extraction.
                logger.warning(f"Cache entry not assemblable (chunk/length mismatch), treating as miss: {cache_key}")
                return None

            cached[ExtractionCacheKeys.MESSAGES] = assembled
            logger.info(f"Cache hit: {cache_key} ({len(assembled)} messages)")
            return cached

        except Exception as e:
            logger.error(f"Failed to get cached extraction for {cache_key}: {e}")
            raise

    async def _assemble_messages(self, parent: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Assemble a parent's full message list from its chunk documents.

        Returns the assembled list, or None when the entry is detectably corrupt
        (the number of chunks present or the total message count does not match
        what the parent recorded). A legacy parent that still embeds an inline
        `messages` array is returned as-is (no chunk lookup).

        Args:
            parent: An extraction_cache parent document.
        """
        cache_key = parent.get(ExtractionCacheKeys.CACHE_KEY)

        # Legacy compatibility: pre-split parents embed the array inline.
        inline = parent.get(ExtractionCacheKeys.MESSAGES)
        if inline is not None and ExtractionCacheKeys.CHUNK_COUNT not in parent:
            return inline

        expected_chunks = parent.get(ExtractionCacheKeys.CHUNK_COUNT, 0)
        expected_messages = parent.get(ExtractionCacheKeys.MESSAGE_COUNT, 0)

        if expected_chunks == 0:
            # No chunks recorded: an empty extraction is valid (zero messages).
            return [] if expected_messages == 0 else None

        # to_list(None) = fetch all matching chunks. The result is naturally
        # bounded by `expected_chunks` (the unique {cache_key, chunk_index} index
        # guarantees one chunk per slot), so this can't run away. Using None
        # rather than a fixed ceiling avoids the footgun where a clipped read
        # would make a valid large entry look "corrupt" and be discarded.
        chunk_docs = await self._chunks.find(
            {ExtractionCacheKeys.CACHE_KEY: cache_key},
            sort=[(ExtractionCacheKeys.CHUNK_INDEX, 1)],
        ).to_list(None)

        if len(chunk_docs) != expected_chunks:
            return None

        messages: list[dict[str, Any]] = []
        for chunk in chunk_docs:
            messages.extend(chunk.get(ExtractionCacheKeys.MESSAGES, []))

        if len(messages) != expected_messages:
            return None

        return messages

    async def set_cached_extraction(self, cache_key: str, chat_name: str, room_id: str, start_date: str, end_date: str, messages: list[dict[str, Any]], extraction_metadata: dict[str, Any] | None = None) -> str:
        """
        Store extraction results in cache, sharding messages across chunk documents.

        Write ordering is deliberate for crash-safety: chunks are (re)written
        FIRST, and the parent's chunk_count is flipped LAST. If the process dies
        mid-write, the parent either does not exist yet or still points at the
        previous chunk_count, so a half-written entry is detected on read
        (chunk-count / length mismatch) and treated as a miss rather than served
        truncated.

        Args:
            cache_key: Unique cache identifier
            chat_name: Name of the chat
            room_id: Matrix room ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            messages: List of extracted message dictionaries
            extraction_metadata: Optional metadata about extraction process

        Returns:
            The cache_key.
        """
        try:
            now = datetime.now(UTC)
            ttl_days = self._settings.database.extraction_cache_ttl_days
            expires_at = now + timedelta(days=ttl_days)

            # Count messages still flagged as encrypted at cache time (i.e. not
            # successfully decrypted). The signal is the Matrix event type, the
            # same predicate the extractor uses (beeper.py); the prior code
            # checked a non-existent "encrypted" boolean key and so was always 0.
            encrypted_count = sum(1 for msg in messages if msg.get(DecryptionResultKeys.TYPE) == MatrixEventType.ROOM_ENCRYPTED)
            chunks = [messages[i : i + EXTRACTION_CACHE_CHUNK_SIZE] for i in range(0, len(messages), EXTRACTION_CACHE_CHUNK_SIZE)]

            # 1) Replace chunks: drop any stale chunks for this key (re-cache of a
            # changed range), then bulk-insert the new ones. Fail-fast on a write
            # error so a partial chunk set never silently backs a parent.
            await self._chunks.delete_many({ExtractionCacheKeys.CACHE_KEY: cache_key})
            if chunks:
                from pymongo.errors import BulkWriteError

                chunk_docs = [
                    {
                        ExtractionCacheKeys.CACHE_KEY: cache_key,
                        ExtractionCacheKeys.CHUNK_INDEX: idx,
                        ExtractionCacheKeys.MESSAGES: chunk,
                        ExtractionCacheKeys.EXPIRES_AT: expires_at,
                    }
                    for idx, chunk in enumerate(chunks)
                ]
                try:
                    await self._chunks.insert_many(chunk_docs, ordered=False)
                except BulkWriteError as e:
                    logger.error(f"Bulk insert of {len(chunk_docs)} extraction-cache chunks failed for {cache_key}: {e.details}")
                    raise

            # 2) Upsert the parent metadata doc LAST. created_at is insert-only
            # ($setOnInsert) so it keeps "first cached at" across re-caches;
            # updated_at and the refreshed TTL/chunk_count are $set. The parent
            # no longer embeds the messages array.
            fields_to_set = {
                ExtractionCacheKeys.CACHE_KEY: cache_key,
                DbFieldKeys.CHAT_NAME: chat_name,
                ExtractionCacheKeys.CHAT_NAME_NORMALIZED: self._normalize_chat_name(chat_name),
                DbFieldKeys.ROOM_ID: room_id,
                ExtractionCacheKeys.START_DATE: start_date,
                ExtractionCacheKeys.END_DATE: end_date,
                ExtractionCacheKeys.MESSAGE_COUNT: len(messages),
                ExtractionCacheKeys.ENCRYPTED_COUNT: encrypted_count,
                ExtractionCacheKeys.EXTRACTION_METADATA: extraction_metadata or {},
                ExtractionCacheKeys.CHUNK_COUNT: len(chunks),
                ExtractionCacheKeys.UPDATED_AT: now,
                ExtractionCacheKeys.EXPIRES_AT: expires_at,
            }
            # Drop any legacy inline messages array left over from a pre-split
            # parent so reads go through the chunk path, not stale embedded data.
            await self.update_one(
                {ExtractionCacheKeys.CACHE_KEY: cache_key},
                {"$set": fields_to_set, "$setOnInsert": {ExtractionCacheKeys.CREATED_AT: now}, "$unset": {ExtractionCacheKeys.MESSAGES: ""}},
                upsert=True,
            )

            logger.info(f"Cached extraction: {cache_key} ({len(messages)} messages in {len(chunks)} chunks, {encrypted_count} encrypted, TTL={ttl_days}d)")

            return cache_key

        except Exception as e:
            logger.error(f"Failed to cache extraction for {cache_key}: {e}")
            raise

    async def invalidate_cache(self, cache_key: str) -> bool:
        """
        Invalidate (delete) a specific cache entry, including its message chunks.

        Args:
            cache_key: Cache identifier to invalidate

        Returns:
            True if the parent cache entry was deleted
        """
        try:
            # Delete chunks first so we never leave orphaned chunks pointing at a
            # removed parent (TTL would eventually catch them, but be explicit).
            await self._chunks.delete_many({ExtractionCacheKeys.CACHE_KEY: cache_key})
            deleted = await self.delete_one({ExtractionCacheKeys.CACHE_KEY: cache_key})

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
        Manually clear all expired cache entries (parents and their chunks).

        Note: TTL index should handle this automatically, but this method
        provides manual cleanup if needed (e.g., for testing or maintenance).

        Returns:
            Number of expired parent entries deleted
        """
        try:
            now = datetime.now(UTC)
            # Chunks carry their own expires_at and TTL, so clear them on the
            # same predicate; parents are counted as the headline number.
            await self._chunks.delete_many({ExtractionCacheKeys.EXPIRES_AT: {"$lt": now}})
            deleted_count = await self.delete_many({ExtractionCacheKeys.EXPIRES_AT: {"$lt": now}})

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
            pipeline = [{"$group": {"_id": f"${DbFieldKeys.CHAT_NAME}", "count": {"$sum": 1}, "total_messages": {"$sum": f"${ExtractionCacheKeys.MESSAGE_COUNT}"}}}, {"$sort": {"count": -1}}, {"$limit": DEFAULT_MAX_QUERY_RESULTS}]

            by_chat = await self.collection.aggregate(pipeline).to_list(DEFAULT_MAX_QUERY_RESULTS)

            # Count expired entries
            now = datetime.now(UTC)
            expired_count = await self.count({ExtractionCacheKeys.EXPIRES_AT: {"$lt": now}})

            stats = {"total_entries": total_entries, "expired_entries": expired_count, "active_entries": total_entries - expired_count, "by_chat": by_chat}

            logger.debug(f"Cache stats: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            raise

    async def get_overlapping_extractions(self, chat_name: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """
        Find cached extractions whose date range overlaps with the requested range.

        Used for incremental extraction: when extending a date range (e.g., Mar 19-Apr 4
        to Mar 19-Apr 6), find existing cached extractions that cover part of the range
        and only extract the delta from the API.

        Each returned parent has its full `messages` list assembled from chunks
        (transparent to the caller). A parent whose chunks are corrupt/partial is
        skipped rather than returned with truncated messages.

        Args:
            chat_name: Name of the chat
            start_date: Requested start date (YYYY-MM-DD)
            end_date: Requested end date (YYYY-MM-DD)

        Returns:
            List of cached extraction documents with overlapping date ranges,
            sorted by start_date ascending, each carrying an assembled `messages` list.
        """
        try:
            normalized_name = self._normalize_chat_name(chat_name)

            # Overlap condition: cached.start <= requested.end AND cached.end >= requested.start
            docs = await self.find_many(
                query={
                    ExtractionCacheKeys.CHAT_NAME_NORMALIZED: normalized_name,
                    ExtractionCacheKeys.START_DATE: {"$lte": end_date},
                    ExtractionCacheKeys.END_DATE: {"$gte": start_date},
                },
                sort=[(ExtractionCacheKeys.START_DATE, 1)],
            )

            hydrated: list[dict[str, Any]] = []
            for doc in docs:
                assembled = await self._assemble_messages(doc)
                if assembled is None:
                    logger.warning(f"Skipping corrupt overlapping cache entry: {doc.get(ExtractionCacheKeys.CACHE_KEY)}")
                    continue
                doc[ExtractionCacheKeys.MESSAGES] = assembled
                hydrated.append(doc)

            if hydrated:
                logger.info(f"Found {len(hydrated)} overlapping extraction cache entries for {chat_name} [{start_date} to {end_date}]")
            else:
                logger.debug(f"No overlapping extraction cache entries for {chat_name}")

            return hydrated

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
