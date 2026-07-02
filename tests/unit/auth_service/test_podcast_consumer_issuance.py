"""Podcast-consumer key issuance endpoint tests (no Docker).

Exercises the request-key and verify handlers directly with in-memory fakes for
the two repositories and the email sender, so the anti-enumeration, per-email
rate-limit, token-validity, and rotate-on-reverify semantics are covered without
MongoDB.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from constants import (
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_GONE,
    PODCAST_CONSUMER_REQUEST_ACK_MESSAGE,
    RAGApiKeyScope,
)
from custom_types.api_schemas import (
    PodcastConsumerKeyRequest,
    PodcastConsumerVerifyRequest,
)
from custom_types.field_keys import PodcastApiConsumerKeys as CKeys
from rag.auth.consumer_tokens import hash_verification_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Disable the shared slowapi limiter so the handler can be called directly.

    The per-IP limit is exercised end-to-end elsewhere; here we test the handler
    logic (anti-enumeration, per-email cap, token flow) without a live app.state.
    """
    from api.rate_limiting import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


class _FakeConsumersRepo:
    def __init__(self):
        self.record: dict | None = None
        self.recent = 0
        self.verified_email = None
        self.verified_key_id = None

    async def count_recent_requests(self, email, *, window_hours=24):
        return self.recent

    async def create_or_refresh_pending(self, email, *, name, verification_token_hash, token_expires_at):
        self.record = {
            CKeys.EMAIL: email,
            CKeys.NAME: name,
            CKeys.VERIFICATION_TOKEN_HASH: verification_token_hash,
            CKeys.VERIFICATION_TOKEN_EXPIRES_AT: token_expires_at,
            CKeys.KEY_ID: (self.record or {}).get(CKeys.KEY_ID),
        }

    async def find_by_token_hash(self, token_hash):
        if self.record and self.record.get(CKeys.VERIFICATION_TOKEN_HASH) == token_hash:
            return self.record
        return None

    async def consume_token(self, token_hash):
        """Simulate the atomic find-one-and-update CAS (single-use).

        Returns the PRE-update snapshot exactly once for a matching, unexpired
        token, then clears the token so a concurrent/repeat call gets None. The
        async yield point before the mutation lets a gather() interleave two
        callers through the same match — only the first past the clear wins.
        """
        if not self.record or self.record.get(CKeys.VERIFICATION_TOKEN_HASH) != token_hash:
            return None
        expires_at = self.record.get(CKeys.VERIFICATION_TOKEN_EXPIRES_AT)
        if expires_at is not None and expires_at < datetime.now(UTC):
            return None
        snapshot = dict(self.record)
        await asyncio.sleep(0)  # widen the race window for the concurrency test
        if self.record.get(CKeys.VERIFICATION_TOKEN_HASH) != token_hash:
            return None  # a concurrent caller already consumed it
        self.record[CKeys.VERIFICATION_TOKEN_HASH] = None
        self.record[CKeys.VERIFICATION_TOKEN_EXPIRES_AT] = None
        return snapshot

    async def mark_verified(self, email, *, key_id):
        self.verified_email = email
        self.verified_key_id = key_id
        self.record[CKeys.KEY_ID] = key_id
        self.record[CKeys.VERIFICATION_TOKEN_HASH] = None


class _FakeKeysRepo:
    def __init__(self):
        self.issued = []
        self.revoked = []
        self._counter = 0

    async def issue_key(self, name, owner, scopes=None):
        self._counter += 1
        key_id = f"key-{self._counter}"
        self.issued.append({"key_id": key_id, "owner": owner, "scopes": scopes})
        return key_id, f"lrag_plaintext-{self._counter}"

    async def revoke(self, key_id):
        self.revoked.append(key_id)
        return True


@pytest.fixture
def wired(monkeypatch):
    """Patch get_database + both repos + email sender into api.podcast_consumers."""
    import api.podcast_consumers as mod

    consumers = _FakeConsumersRepo()
    keys = _FakeKeysRepo()
    sent = []

    async def _fake_db():
        return object()

    monkeypatch.setattr(mod, "get_database", _fake_db)
    monkeypatch.setattr(mod, "PodcastApiConsumersRepository", lambda db: consumers)
    monkeypatch.setattr(mod, "RAGApiKeysRepository", lambda db: keys)

    def _fake_send(email, *, base_url, token):
        sent.append({"email": email, "base_url": base_url, "token": token})

    monkeypatch.setattr(mod, "send_verification_email", _fake_send)
    return mod, consumers, keys, sent


class _Req:
    """Stand-in for the slowapi `request` arg (unused once the limiter is disabled)."""

    client = None
    headers: dict = {}


async def test_request_key_always_202_and_sends(wired):
    mod, consumers, keys, sent = wired
    ack = await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="new@example.com"))
    assert ack.message == PODCAST_CONSUMER_REQUEST_ACK_MESSAGE
    assert len(sent) == 1
    assert consumers.record is not None
    # Token is persisted only as a hash; the plaintext went out in the email.
    assert consumers.record[CKeys.VERIFICATION_TOKEN_HASH] == hash_verification_token(sent[0]["token"])


async def test_request_key_over_email_limit_skips_send_still_202(wired):
    mod, consumers, keys, sent = wired
    consumers.recent = 99  # far over the per-email cap
    ack = await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="spammer@example.com"))
    assert ack.message == PODCAST_CONSUMER_REQUEST_ACK_MESSAGE
    assert sent == []  # no email sent
    assert consumers.record is None  # no token minted


async def test_request_key_delivery_failure_still_202(wired, monkeypatch):
    mod, consumers, keys, sent = wired

    def _boom(email, *, base_url, token):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(mod, "send_verification_email", _boom)
    ack = await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="x@example.com"))
    assert ack.message == PODCAST_CONSUMER_REQUEST_ACK_MESSAGE
    # Token was still persisted (a later request rotates it).
    assert consumers.record is not None


async def test_verify_happy_path_mints_podcast_scoped_key(wired):
    mod, consumers, keys, sent = wired
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="user@example.com"))
    token = sent[0]["token"]

    resp = await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=token))
    assert resp.api_key.startswith("lrag_plaintext-")
    assert resp.mcp_url  # populated from config
    assert len(keys.issued) == 1
    assert keys.issued[0]["scopes"] == [str(RAGApiKeyScope.PODCAST_QUERY)]
    assert consumers.verified_key_id == keys.issued[0]["key_id"]


async def test_verify_invalid_token_400(wired):
    mod, consumers, keys, sent = wired
    with pytest.raises(HTTPException) as exc:
        await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token="never-issued"))
    assert exc.value.status_code == HTTP_STATUS_BAD_REQUEST


async def test_verify_expired_token_410(wired):
    mod, consumers, keys, sent = wired
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="late@example.com"))
    # Force the stored token into the past.
    consumers.record[CKeys.VERIFICATION_TOKEN_EXPIRES_AT] = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(HTTPException) as exc:
        await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=sent[0]["token"]))
    assert exc.value.status_code == HTTP_STATUS_GONE


async def test_reverify_rotates_key(wired):
    mod, consumers, keys, sent = wired
    # First issuance.
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="rot@example.com"))
    first = await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=sent[0]["token"]))
    first_key_id = keys.issued[0]["key_id"]

    # Second request-key rotates the token; verify should revoke the old key and
    # mint a new one.
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="rot@example.com"))
    second = await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=sent[1]["token"]))

    assert second.api_key != first.api_key
    assert first_key_id in keys.revoked  # old key revoked
    assert len(keys.issued) == 2


async def test_concurrent_verifies_mint_exactly_one_key(wired):
    """C2: two concurrent verifies of ONE token -> exactly one key minted.

    Without the atomic consume-token CAS both callers would pass the find and
    both mint a key (the first orphaned). The winner mints; the loser gets a
    400/410 and mints nothing.
    """
    mod, consumers, keys, sent = wired
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="race@example.com"))
    token = sent[0]["token"]

    results = await asyncio.gather(
        mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=token)),
        mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=token)),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, HTTPException)]

    assert len(successes) == 1  # exactly one winner
    assert len(failures) == 1  # the loser is rejected
    assert failures[0].status_code in (HTTP_STATUS_BAD_REQUEST, HTTP_STATUS_GONE)
    assert len(keys.issued) == 1  # single-use enforced: only one key ever minted


async def test_reused_token_after_success_is_rejected(wired):
    """Single-use: replaying a consumed token gets a 400, mints nothing more."""
    mod, consumers, keys, sent = wired
    await mod.request_key(_Req(), PodcastConsumerKeyRequest(email="once@example.com"))
    token = sent[0]["token"]

    await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=token))
    with pytest.raises(HTTPException) as exc:
        await mod.verify_key(_Req(), PodcastConsumerVerifyRequest(token=token))
    assert exc.value.status_code == HTTP_STATUS_BAD_REQUEST
    assert len(keys.issued) == 1
