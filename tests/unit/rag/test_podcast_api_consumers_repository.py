"""PodcastApiConsumersRepository tests (requires MongoDB; auto-skips otherwise).

Covers the isolated-lane primitives: pending upsert + token rotation, the
per-email rolling request count, token-hash lookup, and mark_verified clearing
the token and attaching the minted key_id.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

from datetime import UTC, datetime, timedelta

import pytest

from custom_types.field_keys import PodcastApiConsumerKeys as Keys
from db.repositories.podcast_api_consumers import PodcastApiConsumersRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]

_EMAIL = "repo-test@example.com"


async def _cleanup(repo):
    await repo.collection.delete_many({Keys.EMAIL: _EMAIL})


async def test_pending_upsert_and_token_rotation(db):
    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        await repo.create_or_refresh_pending(_EMAIL, name="A", verification_token_hash="hash1", token_expires_at=exp)
        rec = await repo.find_by_email(_EMAIL)
        assert rec[Keys.VERIFICATION_TOKEN_HASH] == "hash1"
        assert rec[Keys.KEY_ID] is None
        assert rec[Keys.REVOKED] is False

        # Rotate: new token hash replaces the old; still one row.
        await repo.create_or_refresh_pending(_EMAIL, name="A", verification_token_hash="hash2", token_expires_at=exp)
        assert await repo.count({Keys.EMAIL: _EMAIL}) == 1
        rec = await repo.find_by_email(_EMAIL)
        assert rec[Keys.VERIFICATION_TOKEN_HASH] == "hash2"
        assert await repo.find_by_token_hash("hash1") is None
        assert (await repo.find_by_token_hash("hash2"))[Keys.EMAIL] == _EMAIL
    finally:
        await _cleanup(repo)


async def test_count_recent_requests(db):
    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash="h1", token_expires_at=exp)
        await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash="h2", token_expires_at=exp)
        assert await repo.count_recent_requests(_EMAIL, window_hours=24) == 2
        # Unknown email => 0.
        assert await repo.count_recent_requests("nobody@example.com") == 0
    finally:
        await _cleanup(repo)


async def test_mark_verified_clears_token_and_sets_key(db):
    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash="h1", token_expires_at=exp)
        await repo.mark_verified(_EMAIL, key_id="key-xyz")
        rec = await repo.find_by_email(_EMAIL)
        assert rec[Keys.KEY_ID] == "key-xyz"
        assert rec[Keys.VERIFIED_AT] is not None
        assert rec[Keys.VERIFICATION_TOKEN_HASH] is None
        assert await repo.find_by_token_hash("h1") is None
    finally:
        await _cleanup(repo)


async def test_consume_token_atomic_single_use(db):
    """C2: consume_token returns the pre-update doc once, then None (single-use)."""
    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash="consume-h", token_expires_at=exp)

        first = await repo.consume_token("consume-h")
        assert first is not None
        assert first[Keys.VERIFICATION_TOKEN_HASH] == "consume-h"  # pre-update snapshot

        # Token cleared -> a second consume of the same hash gets nothing.
        assert await repo.consume_token("consume-h") is None
        rec = await repo.find_by_email(_EMAIL)
        assert rec[Keys.VERIFICATION_TOKEN_HASH] is None
    finally:
        await _cleanup(repo)


async def test_consume_token_rejects_expired(db):
    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        past = datetime.now(UTC) - timedelta(minutes=1)
        await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash="exp-h", token_expires_at=past)
        assert await repo.consume_token("exp-h") is None  # expired -> no consume
    finally:
        await _cleanup(repo)


async def test_request_timestamps_capped_by_slice(db):
    """H3: request_timestamps is $slice-capped so the array cannot grow unbounded."""
    from constants import PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX

    repo = PodcastApiConsumersRepository(db)
    await _cleanup(repo)
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        for i in range(PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX + 20):
            await repo.create_or_refresh_pending(_EMAIL, name=None, verification_token_hash=f"h{i}", token_expires_at=exp)
        rec = await repo.find_by_email(_EMAIL)
        assert len(rec[Keys.REQUEST_TIMESTAMPS]) == PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX
    finally:
        await _cleanup(repo)


async def test_count_recent_requests_spans_alias_bucket(db):
    """C4: plus-tag / gmail-dot aliases share ONE cap bucket (dedup_key)."""
    repo = PodcastApiConsumersRepository(db)
    emails = ["bucket.user@gmail.com", "bucketuser+1@gmail.com", "b.u.c.k.e.t.user@gmail.com"]

    async def _clean_all():
        from db.repositories.consumer_email import canonicalize_email_for_dedup

        await repo.collection.delete_many({Keys.DEDUP_KEY: canonicalize_email_for_dedup(emails[0])})

    await _clean_all()
    try:
        exp = datetime.now(UTC) + timedelta(minutes=30)
        for i, e in enumerate(emails):
            await repo.create_or_refresh_pending(e, name=None, verification_token_hash=f"a{i}", token_expires_at=exp)
        # Each alias made 1 request; the cap counts across the shared bucket => 3.
        assert await repo.count_recent_requests(emails[0], window_hours=24) == 3
        assert await repo.count_recent_requests("bucketuser+99@gmail.com", window_hours=24) == 3
    finally:
        await _clean_all()
