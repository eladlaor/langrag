"""DailyQueryQuotaRepository tests (requires MongoDB; auto-skips otherwise).

Covers the atomic per-(key_id, day) increment, the per-key limit gate (COST-1),
and the global embedding breaker gate (COST-4b).
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import RAG_GLOBAL_EMBED_QUOTA_KEY_ID
from custom_types.field_keys import RAGQueryQuotaKeys as Keys
from rag.quota.daily_quota import DailyQueryQuotaRepository, _utc_day
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]

_KEY = "quota-test-key"


async def _cleanup(repo):
    await repo.collection.delete_many({Keys.KEY_ID: {"$in": [_KEY, RAG_GLOBAL_EMBED_QUOTA_KEY_ID]}})


async def test_increment_is_atomic_and_daily(db):
    repo = DailyQueryQuotaRepository(db)
    await _cleanup(repo)
    try:
        assert await repo.check_and_increment_key(_KEY, limit=3) is True  # 1
        assert await repo.check_and_increment_key(_KEY, limit=3) is True  # 2
        assert await repo.check_and_increment_key(_KEY, limit=3) is True  # 3
        assert await repo.check_and_increment_key(_KEY, limit=3) is False  # 4 > limit
        row = await repo.find_one({Keys.KEY_ID: _KEY, Keys.DAY: _utc_day()})
        assert row[Keys.COUNT] == 4
        assert row[Keys.EXPIRES_AT] is not None
    finally:
        await _cleanup(repo)


async def test_global_embed_breaker(db):
    repo = DailyQueryQuotaRepository(db)
    await _cleanup(repo)
    try:
        assert await repo.check_and_increment_global_embed(limit=2) is True
        assert await repo.check_and_increment_global_embed(limit=2) is True
        assert await repo.check_and_increment_global_embed(limit=2) is False
    finally:
        await _cleanup(repo)
