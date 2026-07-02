"""
Public podcast-MCP consumer key self-service (langrag.ai/podcasts).

Two fully PUBLIC endpoints (no session cookie, no API key — this is how a
stranger obtains a key):

  POST /api/podcasts/consumers/request-key
      Validate the email, upsert a pending consumer with a single-use verification
      token (hashed at rest, TTL from config), and email the verify link. ALWAYS
      returns 202 with a generic message — for a new email, an already-registered
      email, a per-email rate-limit hit, or a delivery failure — so the surface
      leaks nothing about which emails exist (anti-enumeration). Per-IP abuse is
      capped by slowapi; per-email abuse is capped by a Mongo-backed rolling
      count (skip send + log, still 202).

  POST /api/podcasts/consumers/verify
      Exchange a valid token for a freshly minted PODCAST_QUERY-scoped API key
      (shown ONCE) + the MCP URL. Invalid token -> 400; expired -> 410. If the
      consumer was already verified (has a prior key), the OLD key is REVOKED and
      a NEW one minted (rotate-on-reverify), so a re-request fully rotates the
      credential.

These records live in `podcast_api_consumers`, never in `users`: a consumer has
no app account. The key is scoped to PODCAST_QUERY so it can reach ONLY the
public podcast MCP tools, enforced server-side at the MCP tool boundary.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from config import get_settings
from constants import (
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_GONE,
    PODCAST_CONSUMER_KEY_NAME,
    PODCAST_CONSUMER_KEY_OWNER_PREFIX,
    PODCAST_CONSUMER_REQUEST_ACK_MESSAGE,
    PODCAST_CONSUMER_TOKEN_EXPIRED_MESSAGE,
    PODCAST_CONSUMER_TOKEN_INVALID_MESSAGE,
    ROUTE_PODCAST_CONSUMER_REQUEST_KEY,
    ROUTE_PODCAST_CONSUMER_VERIFY,
    RAGApiKeyScope,
)
from custom_types.api_schemas import (
    PodcastConsumerKeyRequest,
    PodcastConsumerKeyRequestAck,
    PodcastConsumerVerifyRequest,
    PodcastConsumerVerifyResponse,
)
from custom_types.field_keys import PodcastApiConsumerKeys
from api.rate_limiting import (
    RATE_PODCAST_CONSUMER_REQUEST_KEY,
    RATE_PODCAST_CONSUMER_VERIFY,
    limiter,
)
from core.delivery.podcast_consumer_email import send_verification_email
from db.connection import get_database
from db.repositories.podcast_api_consumers import PodcastApiConsumersRepository
from db.repositories.rag_api_keys import RAGApiKeysRepository
from db.repositories.users import normalize_email
from observability.app import get_logger
from rag.auth.consumer_tokens import (
    generate_verification_token,
    hash_verification_token,
    verify_token_matches,
)

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["podcast-consumers"])

_REQUEST_WINDOW_HOURS = 24


@router.post(ROUTE_PODCAST_CONSUMER_REQUEST_KEY, response_model=PodcastConsumerKeyRequestAck, status_code=202)
@limiter.limit(RATE_PODCAST_CONSUMER_REQUEST_KEY)
async def request_key(request: Request, body: PodcastConsumerKeyRequest) -> PodcastConsumerKeyRequestAck:
    """Start issuance: upsert a pending consumer + email a verification link.

    ALWAYS returns 202 with the generic message. `request: Request` is required
    by slowapi (per-IP limit) and is otherwise unused here.
    """
    email = normalize_email(str(body.email))
    settings = get_settings().rag
    try:
        db = await get_database()
        repo = PodcastApiConsumersRepository(db)

        # Per-email rolling-window cap. Over the limit: skip the send + log, but
        # still return the generic 202 (no enumeration signal to the caller).
        recent = await repo.count_recent_requests(email, window_hours=_REQUEST_WINDOW_HOURS)
        if recent >= settings.podcast_consumer_max_requests_per_email_per_day:
            logger.warning(
                "Podcast consumer request-key skipped: per-email rate limit",
                extra={"event": "podcast_consumer_email_rate_limited", "function": "request_key", "email": email, "recent": recent},
            )
            return PodcastConsumerKeyRequestAck(message=PODCAST_CONSUMER_REQUEST_ACK_MESSAGE)

        token = generate_verification_token()
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.podcast_consumer_token_ttl_minutes)
        await repo.create_or_refresh_pending(
            email,
            name=body.name,
            verification_token_hash=hash_verification_token(token),
            token_expires_at=expires_at,
        )

        # Delivery failure is logged at error (fail-fast internally) but the
        # response stays 202 (opaque externally). The token is already persisted,
        # so a later retry with a fresh request-key rotates it.
        try:
            send_verification_email(email, base_url=settings.podcast_consumer_verify_base_url, token=token)
        except Exception as e:
            logger.error(
                "Podcast consumer verification email delivery failed",
                extra={"event": "podcast_consumer_email_delivery_failed", "function": "request_key", "email": email, "error": str(e)},
            )

        return PodcastConsumerKeyRequestAck(message=PODCAST_CONSUMER_REQUEST_ACK_MESSAGE)
    except Exception as e:
        # Never leak a 500 stack to this public surface; log and return the same
        # opaque 202 so failures are indistinguishable from success to a prober.
        logger.error(
            "Podcast consumer request-key failed",
            extra={"event": "podcast_consumer_request_failed", "function": "request_key", "email": email, "error": str(e)},
        )
        return PodcastConsumerKeyRequestAck(message=PODCAST_CONSUMER_REQUEST_ACK_MESSAGE)


@router.post(ROUTE_PODCAST_CONSUMER_VERIFY, response_model=PodcastConsumerVerifyResponse)
@limiter.limit(RATE_PODCAST_CONSUMER_VERIFY)
async def verify_key(request: Request, body: PodcastConsumerVerifyRequest) -> PodcastConsumerVerifyResponse:
    """Exchange a valid single-use token for a freshly minted API key (once).

    Invalid/unknown token -> 400; expired token -> 410. On success mints a
    PODCAST_QUERY-scoped key, revoking any prior key for the same consumer
    (rotate-on-reverify), marks the consumer verified, and invalidates the token.

    Single-use is enforced ATOMICALLY: `consume_token` is a find-one-and-update
    CAS that clears the token in the same op that matches it, so two concurrent
    verifies of one token cannot both mint a key — only the CAS winner does. The
    verify endpoint is itself rate-limited (per-IP) so a leaked link cannot be
    replayed to hammer minting/revocation. `request: Request` is required by
    slowapi and is otherwise unused here.
    """
    settings = get_settings().rag
    try:
        db = await get_database()
        consumers = PodcastApiConsumersRepository(db)
        keys = RAGApiKeysRepository(db)

        token_hash = hash_verification_token(body.token)

        # Atomic single-use consumption: only the winner of the CAS gets the
        # pre-update record (and thus mints a key). A loser (already-consumed
        # token, or a concurrent verify that won) gets None.
        record = await consumers.consume_token(token_hash)
        if record is None:
            # Distinguish 400 (unknown/consumed) from 410 (expired) for the UI.
            # A row that still exists but whose token expired -> 410; otherwise
            # 400. This read leaks nothing: the caller already holds the token.
            existing = await consumers.find_by_token_hash(token_hash)
            expires_at = existing.get(PodcastApiConsumerKeys.VERIFICATION_TOKEN_EXPIRES_AT) if existing else None
            if expires_at is not None and _as_aware(expires_at) < datetime.now(UTC):
                logger.warning(
                    "Podcast consumer verify rejected: token expired",
                    extra={"event": "podcast_consumer_verify_expired", "function": "verify_key"},
                )
                raise HTTPException(status_code=HTTP_STATUS_GONE, detail=PODCAST_CONSUMER_TOKEN_EXPIRED_MESSAGE)
            logger.warning(
                "Podcast consumer verify rejected: unknown or already-consumed token",
                extra={"event": "podcast_consumer_verify_unknown_token", "function": "verify_key"},
            )
            raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail=PODCAST_CONSUMER_TOKEN_INVALID_MESSAGE)

        # Constant-time re-check against the pre-update stored hash. consume_token
        # matched on the hash, but this keeps the auth decision on a timing-safe
        # primitive (defense-in-depth against a hash-lookup timing oracle).
        stored_hash = record.get(PodcastApiConsumerKeys.VERIFICATION_TOKEN_HASH) or ""
        if not verify_token_matches(body.token, stored_hash):
            logger.warning(
                "Podcast consumer verify rejected: token mismatch",
                extra={"event": "podcast_consumer_verify_mismatch", "function": "verify_key"},
            )
            raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail=PODCAST_CONSUMER_TOKEN_INVALID_MESSAGE)

        email = record[PodcastApiConsumerKeys.EMAIL]

        # Won the CAS: rotate-on-reverify (revoke the previous key, if any) then
        # mint the new one so at most one live key exists per consumer. Both
        # happen only on this winning path.
        prior_key_id = record.get(PodcastApiConsumerKeys.KEY_ID)
        if prior_key_id:
            await keys.revoke(prior_key_id)
            logger.info(
                "Revoked prior podcast consumer key on reverify",
                extra={"event": "podcast_consumer_key_rotated", "function": "verify_key", "email": email, "prior_key_id": prior_key_id},
            )

        key_id, plaintext = await keys.issue_key(
            name=PODCAST_CONSUMER_KEY_NAME,
            owner=f"{PODCAST_CONSUMER_KEY_OWNER_PREFIX}{email}",
            scopes=[str(RAGApiKeyScope.PODCAST_QUERY)],
        )
        await consumers.mark_verified(email, key_id=key_id)

        logger.info(
            "Podcast consumer verified; key issued",
            extra={"event": "podcast_consumer_key_issued", "function": "verify_key", "email": email, "key_id": key_id},
        )
        return PodcastConsumerVerifyResponse(api_key=plaintext, mcp_url=settings.mcp_public_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Podcast consumer verify failed",
            extra={"event": "podcast_consumer_verify_failed", "function": "verify_key", "error": str(e)},
        )
        raise


def _as_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive Mongo datetime to UTC-aware for comparison."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
