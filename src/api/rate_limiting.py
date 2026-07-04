"""
Rate limiting configuration for FastAPI.

Provides middleware and decorators for API rate limiting
to prevent abuse of expensive LLM operations.
"""

import hashlib
import logging

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.client_ip import resolve_client_ip
from config import get_settings
from constants import (
    RAG_API_KEY_BEARER_SCHEME,
    RAG_API_KEY_HEADER,
)

logger = logging.getLogger(__name__)


def _hashed_key_bucket(api_key: str) -> str:
    """Bucket key derived from an API key without embedding the raw secret.

    The raw key must never land verbatim in limiter storage, logs, or
    diagnostics, so we bucket on a SHA-256 prefix. This is intentionally a plain
    (unpeppered) digest: a bucket key needs uniqueness, not the replay
    protection of hash_api_key() — and hash_api_key() would raise when
    RAG_API_KEY_PEPPER is unset, which is wrong for this non-secret use.
    """
    return f"key:{hashlib.sha256(api_key.encode('utf-8')).hexdigest()[:32]}"


def _rate_limit_key(request: Request) -> str:
    """Per-caller rate-limit key: prefer the RAG API key, fall back to client IP.

    Quotas become per-caller for authenticated RAG traffic while preserving
    IP-based limits for everything else (existing behaviour unchanged). The API
    key is hashed before use so the raw secret never enters the limiter store.
    """
    api_key = request.headers.get(RAG_API_KEY_HEADER)
    if api_key:
        return _hashed_key_bucket(api_key)

    auth = request.headers.get("Authorization", "")
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == RAG_API_KEY_BEARER_SCHEME.lower():
        return _hashed_key_bucket(parts[1].strip())

    return f"ip:{resolve_client_ip(request)}"


# Single application-wide limiter used by all decorators.
#
# Counters live in-memory per process by default, which is correct for the
# single-worker deployment (Dockerfile runs one uvicorn process). If you ever
# run multiple uvicorn workers or app replicas, set API_RATE_LIMIT_STORAGE_URI
# to a shared store (e.g. redis://...); otherwise each process keeps its own
# counter and the effective limit becomes N× the configured value.
_storage_uri = get_settings().api.rate_limit_storage_uri or None
limiter = Limiter(key_func=_rate_limit_key, storage_uri=_storage_uri)


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI application.

    Rate Limits:
    - Newsletter generation: 10/minute (expensive LLM operations)
    - Batch job queries: 60/minute
    - Health checks: 120/minute
    - Default: 30/minute

    The limiter uses client IP address as the rate limit key.
    In production behind a proxy, ensure X-Forwarded-For is trusted.

    Args:
        app: FastAPI application instance
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        """Handle rate limit exceeded errors with JSON response."""
        # request.client is None for some ASGI transports; guard so the 429 is
        # never masked as a 500 by an AttributeError in the handler itself.
        client_host = request.client.host if request.client else "unknown"
        logger.warning(f"Rate limit exceeded: {client_host} on {request.url.path}")
        return JSONResponse(status_code=429, content={"error": "rate_limit_exceeded", "message": f"Too many requests. {exc.detail}", "retry_after": getattr(exc, "retry_after", None)}, headers={"Retry-After": str(getattr(exc, "retry_after", 60))})

    logger.info("Rate limiting configured for API endpoints")


# Rate limit constants for easy reference in route decorators
RATE_NEWSLETTER_GENERATION = "10/minute"
RATE_BATCH_JOB_QUERY = "60/minute"
RATE_HEALTH_CHECK = "120/minute"
RATE_DEFAULT = "30/minute"
# Unauthenticated self-signup + access-request POSTs. Tight to deter abuse /
# enumeration while leaving headroom for a legitimate human retrying.
RATE_SIGNUP = "10/minute"
RATE_ACCESS_REQUEST = "5/minute"
# Login. Throttles credential-stuffing / brute force AND caps the CPU/memory DoS
# amplification of the deliberately-expensive argon2id verify run per attempt.
RATE_LOGIN = "10/minute"
# Public podcast-MCP key issuance (request-key). Per-IP slowapi cap so a single
# source cannot mint-spam the endpoint or blast verification emails. This is the
# per-IP leg; the per-email leg is enforced separately (Mongo-backed count in the
# consumers repo) because slowapi keys on IP/API-key, not on request-body email.
RATE_PODCAST_CONSUMER_REQUEST_KEY = "5/hour"
# Public podcast-MCP key issuance (verify). Verify MINTS a credential, so it must
# be throttled just like request-key: without this, a leaked/guessed token (or a
# stolen verify link) could be replayed to hammer key minting / prior-key
# revocation. Per-IP cap; a legitimate human clicks the link once or twice.
RATE_PODCAST_CONSUMER_VERIFY = "10/hour"
