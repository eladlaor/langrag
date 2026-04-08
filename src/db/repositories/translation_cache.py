"""
Translation Cache Repository

Caches per-message translations to enable incremental cross-run reuse.
When a date range is extended, only new (uncached) messages need translation.

Cache key: (matrix_event_id, target_language) — globally unique per message + language pair.
Content hash (SHA256) detects message edits that require re-translation.
"""

import hashlib
import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from db.repositories.base import BaseRepository
from config import get_settings
from constants import COLLECTION_TRANSLATION_CACHE
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Compute SHA256 hash of message content for edit detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TranslationCacheRepository(BaseRepository):
    """
    Repository for caching per-message translations across pipeline runs.

    Enables incremental translation: when extending a date range (e.g., Mar 19-Apr 4
    to Mar 19-Apr 6), only the new messages from Apr 5-6 are sent to the LLM.
    Previously translated messages are served from cache.

    Cache Key: (matrix_event_id, target_language)
    Edit Detection: SHA256 content_hash — if content changed, message is re-translated.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_TRANSLATION_CACHE)
        self._settings = get_settings()

    async def get_cached_translations(
        self,
        matrix_event_ids: list[str],
        target_language: str,
    ) -> dict[str, dict[str, Any]]:
        """
        Bulk-lookup cached translations by matrix_event_id and target language.

        Args:
            matrix_event_ids: List of Matrix event IDs to look up
            target_language: Target language (e.g., "english")

        Returns:
            Dict mapping matrix_event_id -> {translated_content, content_hash}
            Only includes cache hits (missing IDs are omitted).
        """
        if not matrix_event_ids:
            return {}

        try:
            docs = await self.find_many(
                query={
                    DbFieldKeys.MATRIX_EVENT_ID: {"$in": matrix_event_ids},
                    DbFieldKeys.TARGET_LANGUAGE: target_language,
                },
                projection={
                    DbFieldKeys.MATRIX_EVENT_ID: 1,
                    DbFieldKeys.TRANSLATED_CONTENT: 1,
                    DbFieldKeys.CONTENT_HASH: 1,
                    "_id": 0,
                },
            )

            result = {}
            for doc in docs:
                event_id = doc[DbFieldKeys.MATRIX_EVENT_ID]
                result[event_id] = {
                    DbFieldKeys.TRANSLATED_CONTENT: doc[DbFieldKeys.TRANSLATED_CONTENT],
                    DbFieldKeys.CONTENT_HASH: doc[DbFieldKeys.CONTENT_HASH],
                }

            logger.info(
                f"Translation cache lookup: {len(result)}/{len(matrix_event_ids)} hits "
                f"for target_language={target_language}"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to lookup translation cache: {e}")
            raise

    async def store_translations(
        self,
        translations: list[dict[str, Any]],
        target_language: str,
        chat_name: str,
        data_source_name: str,
    ) -> int:
        """
        Bulk-upsert translated messages into cache.

        Each translation dict must contain:
            - matrix_event_id: str
            - original_content: str
            - translated_content: str

        Args:
            translations: List of translation dicts to cache
            target_language: Target language (e.g., "english")
            chat_name: Chat name for debugging/querying
            data_source_name: Data source name

        Returns:
            Number of documents upserted
        """
        if not translations:
            return 0

        try:
            now = datetime.now(UTC)
            ttl_days = self._settings.database.translation_cache_ttl_days
            expires_at = now + timedelta(days=ttl_days)

            operations = []
            for t in translations:
                matrix_event_id = t[DbFieldKeys.MATRIX_EVENT_ID]
                original_content = t[DbFieldKeys.CONTENT]
                translated_content = t[DbFieldKeys.TRANSLATED_CONTENT]
                content_hash = compute_content_hash(original_content)

                operations.append(
                    UpdateOne(
                        {
                            DbFieldKeys.MATRIX_EVENT_ID: matrix_event_id,
                            DbFieldKeys.TARGET_LANGUAGE: target_language,
                        },
                        {
                            "$set": {
                                DbFieldKeys.MATRIX_EVENT_ID: matrix_event_id,
                                DbFieldKeys.TARGET_LANGUAGE: target_language,
                                DbFieldKeys.CHAT_NAME: chat_name,
                                DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                                DbFieldKeys.CONTENT: original_content,
                                DbFieldKeys.TRANSLATED_CONTENT: translated_content,
                                DbFieldKeys.CONTENT_HASH: content_hash,
                                DbFieldKeys.TRANSLATED_AT: now,
                                DbFieldKeys.EXPIRES_AT: expires_at,
                            }
                        },
                        upsert=True,
                    )
                )

            if operations:
                result = await self.collection.bulk_write(operations, ordered=False)
                upserted_count = result.upserted_count + result.modified_count
                logger.info(
                    f"Translation cache store: {upserted_count} entries "
                    f"({result.upserted_count} new, {result.modified_count} updated) "
                    f"for chat={chat_name}, target_language={target_language}"
                )
                return upserted_count

            return 0

        except Exception as e:
            logger.error(f"Failed to store translations in cache: {e}")
            raise

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the translation cache."""
        try:
            total_entries = await self.count()

            pipeline = [
                {
                    "$group": {
                        "_id": {
                            DbFieldKeys.CHAT_NAME: f"${DbFieldKeys.CHAT_NAME}",
                            DbFieldKeys.TARGET_LANGUAGE: f"${DbFieldKeys.TARGET_LANGUAGE}",
                        },
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"count": -1}},
            ]
            by_chat_language = await self.collection.aggregate(pipeline).to_list(length=None)

            now = datetime.now(UTC)
            expired_count = await self.count({DbFieldKeys.EXPIRES_AT: {"$lt": now}})

            return {
                "total_entries": total_entries,
                "expired_entries": expired_count,
                "active_entries": total_entries - expired_count,
                "by_chat_language": by_chat_language,
            }

        except Exception as e:
            logger.error(f"Failed to get translation cache stats: {e}")
            raise

    async def invalidate_chat_cache(self, chat_name: str, target_language: str | None = None) -> int:
        """
        Invalidate all cached translations for a specific chat.

        Args:
            chat_name: Chat name to invalidate
            target_language: Optional language filter (None = all languages)

        Returns:
            Number of entries deleted
        """
        try:
            query: dict[str, Any] = {DbFieldKeys.CHAT_NAME: chat_name}
            if target_language:
                query[DbFieldKeys.TARGET_LANGUAGE] = target_language

            deleted_count = await self.delete_many(query)
            logger.info(f"Invalidated {deleted_count} translation cache entries for chat={chat_name}")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to invalidate translation cache for chat={chat_name}: {e}")
            raise
