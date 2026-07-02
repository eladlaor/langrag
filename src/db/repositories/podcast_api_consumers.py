"""
Podcast API Consumers Repository

CRUD for the `podcast_api_consumers` collection: the isolated consumer lane for
external AI engineers who query the podcast corpus via mcp.langrag.ai. This is
deliberately SEPARATE from `users` — a consumer has no app account, no password,
no session, no app authorization. The PODCAST_QUERY-scoped API key it is granted
(minted into `rag_api_keys`, referenced here by key_id) IS its identity.

A verification token is stored only as its HMAC hash with a TTL; a re-request for
the same email rotates the token (and, on the next verify, rotates the key —
revoking the previous one). Anti-enumeration and rate-limit decisions are made in
the API layer; this repo exposes the primitives it needs.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from constants import (
    COLLECTION_PODCAST_API_CONSUMERS,
    PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX,
)
from custom_types.field_keys import PodcastApiConsumerKeys as Keys
from db.repositories.base import BaseRepository
from db.repositories.consumer_email import canonicalize_email_for_dedup
from db.repositories.users import normalize_email

logger = logging.getLogger(__name__)


class PodcastApiConsumersRepository(BaseRepository):
    """Repository for the isolated podcast-MCP consumer lane."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_PODCAST_API_CONSUMERS)

    async def count_recent_requests(self, email: str, *, window_hours: int = 24) -> int:
        """Return how many request-key calls this email's bucket made in the window.

        Backs the per-email issuance rate limit. Counts persisted
        request_timestamps newer than (now - window) across the whole
        CANONICAL dedup bucket (every alias of the same mailbox — plus-tags and
        gmail-dot variants — shares one cap), not just the exact address, so a
        `user+N@x.com` / `u.ser@gmail.com` alias cannot bypass the cap. Returns 0
        for an unknown bucket. Fail-fast: DB errors propagate (the caller must not
        silently under-count and let a mint-spam through).
        """
        try:
            dedup_key = canonicalize_email_for_dedup(email)
            cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
            records = await self.find_many({Keys.DEDUP_KEY: dedup_key})
            total = 0
            for record in records:
                stamps = record.get(Keys.REQUEST_TIMESTAMPS, []) or []
                total += sum(1 for ts in stamps if _as_aware(ts) >= cutoff)
            return total
        except Exception as e:
            logger.error(
                "count_recent_requests failed",
                extra={"event": "podcast_consumer_count_failed", "function": "count_recent_requests", "error": str(e)},
            )
            raise

    async def create_or_refresh_pending(
        self,
        email: str,
        *,
        name: str | None,
        verification_token_hash: str,
        token_expires_at: datetime,
    ) -> None:
        """Upsert a pending consumer with a fresh single-use verification token.

        Idempotent by email (unique index). A repeat call ROTATES the token:
        overwrites the hash + expiry and records the request timestamp. Does not
        touch key_id / verified_at (a re-request before verify keeps any prior
        verified state until the NEW token is verified, at which point the API
        layer rotates the key).
        """
        try:
            email = normalize_email(email)
            dedup_key = canonicalize_email_for_dedup(email)
            now = datetime.now(UTC)
            await self.update_one(
                {Keys.EMAIL: email},
                {
                    "$set": {
                        Keys.NAME: name,
                        Keys.DEDUP_KEY: dedup_key,
                        Keys.VERIFICATION_TOKEN_HASH: verification_token_hash,
                        Keys.VERIFICATION_TOKEN_EXPIRES_AT: token_expires_at,
                    },
                    # $slice caps the persisted array at the last N timestamps so a
                    # persistent abuser (still 202'd while rate-limited) cannot grow
                    # the document without bound. N > the daily cap, so the rolling
                    # count is never under-reported by the trim.
                    "$push": {Keys.REQUEST_TIMESTAMPS: {"$each": [now], "$slice": -PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX}},
                    "$setOnInsert": {
                        Keys.EMAIL: email,
                        Keys.KEY_ID: None,
                        Keys.CREATED_AT: now,
                        Keys.VERIFIED_AT: None,
                        Keys.LAST_USED_AT: None,
                        Keys.QUOTA: None,
                        Keys.REVOKED: False,
                    },
                },
                upsert=True,
            )
            logger.info(
                "Upserted pending podcast consumer",
                extra={"event": "podcast_consumer_pending", "function": "create_or_refresh_pending", "email": email},
            )
        except Exception as e:
            logger.error(
                "create_or_refresh_pending failed",
                extra={"event": "podcast_consumer_pending_failed", "function": "create_or_refresh_pending", "email": email, "error": str(e)},
            )
            raise

    async def find_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        """Find a consumer by its current verification-token hash, or None."""
        try:
            return await self.find_one({Keys.VERIFICATION_TOKEN_HASH: token_hash})
        except Exception as e:
            logger.error(
                "find_by_token_hash failed",
                extra={"event": "podcast_consumer_token_lookup_failed", "function": "find_by_token_hash", "error": str(e)},
            )
            raise

    async def consume_token(self, token_hash: str) -> dict[str, Any] | None:
        """Atomically consume a valid, unexpired verification token (single-use CAS).

        Matches a consumer whose CURRENT token hash equals `token_hash` AND whose
        token has not expired, and in the SAME atomic operation clears the token
        (hash + expiry -> None). Returns the pre-update document (so the caller
        sees the prior key_id to rotate) on the winning call, or None if no such
        live token exists.

        This closes the verify race: two concurrent verifies of one token both
        pass a plain find, but only ONE find_one_and_update matches the still-set
        hash — the loser sees the already-cleared token and gets None, so it mints
        nothing. The key is minted ONLY by the caller that wins here.

        A None return is deliberately ambiguous between "unknown token" and
        "expired token"; the caller re-derives the exact 400-vs-410 distinction
        from a follow-up read (verify is not anti-enumeration — the caller holds
        the token).
        """
        try:
            now = datetime.now(UTC)
            return await self.collection.find_one_and_update(
                {
                    Keys.VERIFICATION_TOKEN_HASH: token_hash,
                    Keys.VERIFICATION_TOKEN_EXPIRES_AT: {"$gt": now},
                },
                {
                    "$set": {
                        Keys.VERIFICATION_TOKEN_HASH: None,
                        Keys.VERIFICATION_TOKEN_EXPIRES_AT: None,
                    }
                },
                return_document=False,  # BEFORE: pre-update doc, carries prior key_id
            )
        except Exception as e:
            logger.error(
                "consume_token failed",
                extra={"event": "podcast_consumer_consume_token_failed", "function": "consume_token", "error": str(e)},
            )
            raise

    async def mark_verified(self, email: str, *, key_id: str) -> None:
        """Mark the consumer verified, attach the minted key_id, invalidate token.

        Clears the verification-token hash/expiry (single-use consumed) and sets
        revoked=False. This is called AFTER the new key is minted so the record
        always points at a live key.
        """
        try:
            email = normalize_email(email)
            await self.update_one(
                {Keys.EMAIL: email},
                {
                    "$set": {
                        Keys.KEY_ID: key_id,
                        Keys.VERIFIED_AT: datetime.now(UTC),
                        Keys.REVOKED: False,
                        Keys.VERIFICATION_TOKEN_HASH: None,
                        Keys.VERIFICATION_TOKEN_EXPIRES_AT: None,
                    }
                },
            )
            logger.info(
                "Marked podcast consumer verified",
                extra={"event": "podcast_consumer_verified", "function": "mark_verified", "email": email, "key_id": key_id},
            )
        except Exception as e:
            logger.error(
                "mark_verified failed",
                extra={"event": "podcast_consumer_verify_failed", "function": "mark_verified", "email": email, "error": str(e)},
            )
            raise

    async def touch_last_used(self, key_id: str) -> None:
        """Best-effort update of last_used_at for the consumer owning key_id.

        Fire-and-forget on the hot MCP path: a failure here must never fail an
        otherwise-authorized tool call, so it is logged (warning) and swallowed.
        """
        try:
            await self.update_one(
                {Keys.KEY_ID: key_id},
                {"$set": {Keys.LAST_USED_AT: datetime.now(UTC)}},
            )
        except Exception as e:
            logger.warning(
                "touch_last_used failed (non-critical)",
                extra={"event": "podcast_consumer_touch_failed", "function": "touch_last_used", "key_id": key_id, "error": str(e)},
            )

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """Return the consumer record for an email (normalized), or None."""
        try:
            return await self.find_one({Keys.EMAIL: normalize_email(email)})
        except Exception as e:
            logger.error(
                "find_by_email failed",
                extra={"event": "podcast_consumer_email_lookup_failed", "function": "find_by_email", "error": str(e)},
            )
            raise


def _as_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive Mongo datetime to UTC-aware for comparison.

    PyMongo returns naive UTC datetimes by default; comparing them against an
    aware `now` would raise. Treat a naive value as already-UTC.
    """
    return value if value.tzinfo else value.replace(tzinfo=UTC)
