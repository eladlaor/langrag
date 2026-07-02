"""
Per-key daily query-quota counter + global daily embedding circuit breaker.

Backs COST-1 (per-key daily query quota, enforced BEFORE the owner-paid embedding
call) and COST-4b (a global daily embedding-count circuit breaker bounding total
exposure regardless of key count). Both are the same primitive: an atomic
per-(key_id, UTC day) counter in ``rag_query_quota``.

The counter is incremented atomically with ``find_one_and_update`` ($inc, upsert)
so concurrent admissions cannot race past the cap. Each row carries an ``expires_at``
one day past its day so a TTL index self-cleans old counters (see db.indexes).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from constants import COLLECTION_RAG_QUERY_QUOTA, RAG_GLOBAL_EMBED_QUOTA_KEY_ID
from custom_types.field_keys import RAGQueryQuotaKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


def _utc_day(now: datetime | None = None) -> str:
    """Return the current UTC day as an ISO date string (the counter bucket key)."""
    return (now or datetime.now(UTC)).date().isoformat()


class DailyQueryQuotaRepository(BaseRepository):
    """Atomic per-(key_id, UTC day) counter store for query/embedding quotas."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_QUERY_QUOTA)

    async def _increment(self, key_id: str, *, day: str) -> int:
        """Atomically bump and return the post-increment count for (key_id, day)."""
        try:
            expires_at = datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(days=2)
            doc = await self.collection.find_one_and_update(
                {Keys.KEY_ID: key_id, Keys.DAY: day},
                {
                    "$inc": {Keys.COUNT: 1},
                    "$setOnInsert": {
                        Keys.KEY_ID: key_id,
                        Keys.DAY: day,
                        Keys.EXPIRES_AT: expires_at,
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            return int(doc[Keys.COUNT])
        except Exception as e:
            logger.error(
                "Failed to increment daily quota counter",
                extra={"event": "quota_increment_failed", "function": "_increment", "key_id": key_id, "day": day, "error": str(e)},
            )
            raise

    async def check_and_increment_key(self, key_id: str, *, limit: int) -> bool:
        """Reserve one query for ``key_id`` today; return False if over ``limit``.

        Atomically increments first, then compares: this is the standard
        reserve-then-check so concurrent callers cannot both slip past the cap.
        The (limit+1)th caller in a day sees post-count > limit and is rejected;
        its increment is harmless (the counter is day-scoped and TTL-cleaned).
        """
        post = await self._increment(key_id, day=_utc_day())
        if post > limit:
            logger.warning(
                "Per-key daily query quota exceeded",
                extra={"event": "quota_exceeded", "key_id": key_id, "count": post, "limit": limit},
            )
            return False
        return True

    async def check_and_increment_global_embed(self, *, limit: int) -> bool:
        """Reserve one embedding against the global daily cap; False if tripped.

        The circuit breaker (COST-4b): a single sentinel row counts embeddings
        across ALL keys for the day. Past ``limit`` the breaker is open and the
        search hard-stops with a clean error.
        """
        post = await self._increment(RAG_GLOBAL_EMBED_QUOTA_KEY_ID, day=_utc_day())
        if post > limit:
            logger.error(
                "Global daily embedding circuit breaker tripped",
                extra={"event": "global_embed_breaker_open", "count": post, "limit": limit},
            )
            return False
        return True
