"""
Search-path admission control for the public podcast-MCP surface.

Orchestrates the two per-key cost guards that MUST run BEFORE the owner-paid
embedding call on ``search_podcasts``:

  - COST-2: an in-process per-key sliding-window rate limit (fast, in-memory).
  - COST-1: a per-key daily query quota (durable, Mongo-backed, atomic).

Order matters: the cheap in-memory rate limit runs first so a flood is shed
without a DB round-trip; only an admitted-by-rate request touches the quota
counter. Either rejection raises ``QueryAdmissionError`` (a clean tool error);
no embedding call happens on the rejected path.

The rate limiter is a process-wide singleton (per-process, like the concurrency
guard) built lazily from settings so tests can reset it.
"""

from __future__ import annotations

import logging

from config import get_settings
from constants import (
    RAG_GLOBAL_ANON_QUOTA_KEY_ID,
    RAG_REJECT_REASON_ANON_GLOBAL_BREAKER,
)
from rag.quota.daily_quota import DailyQueryQuotaRepository
from rag.quota.rate_limiter import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)


class QueryAdmissionError(Exception):
    """Raised when a search is shed by the per-key rate limit or daily quota.

    A distinct type so the MCP layer surfaces it as a clean tool error and tests
    can assert the pre-embedding rejection specifically. Carries a machine
    ``reason`` for reject observability (OBS-2).
    """

    def __init__(self, message: str, *, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


# Reject reason labels (behavior-affecting: consumed by reject observability).
ADMISSION_REASON_RATE_LIMIT = "rate_limit_exceeded"
ADMISSION_REASON_DAILY_QUOTA = "daily_quota_exceeded"


_rate_limiter: SlidingWindowRateLimiter | None = None
_anon_rate_limiter: SlidingWindowRateLimiter | None = None


def _key_signup_hint() -> str:
    """Point an over-limit anonymous caller at the free keyed tier (URL from config)."""
    return f"Get a free API key at {get_settings().rag.podcast_consumer_verify_base_url} for higher limits."


def _get_rate_limiter() -> SlidingWindowRateLimiter:
    """Build (once) and return the process-wide per-key rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        rag = get_settings().rag
        _rate_limiter = SlidingWindowRateLimiter(
            max_per_window=rag.mcp_query_rate_per_min,
            window_seconds=60.0,
        )
    return _rate_limiter


def _get_anon_rate_limiter() -> SlidingWindowRateLimiter:
    """Build (once) and return the process-wide anonymous-lane (per-IP) rate limiter."""
    global _anon_rate_limiter
    if _anon_rate_limiter is None:
        rag = get_settings().rag
        _anon_rate_limiter = SlidingWindowRateLimiter(
            max_per_window=rag.mcp_anon_query_rate_per_min,
            window_seconds=60.0,
        )
    return _anon_rate_limiter


async def enforce_query_admission(key_id: str, *, quota_repo: DailyQueryQuotaRepository) -> None:
    """Enforce rate limit then daily quota for ``key_id``. Raise on rejection.

    Runs BEFORE any embedding. Raises ``QueryAdmissionError`` with a reason so no
    owner-paid embedding call is made on a shed request.
    """
    rag = get_settings().rag

    if not _get_rate_limiter().allow(key_id):
        raise QueryAdmissionError(
            f"Rate limit exceeded: max {rag.mcp_query_rate_per_min} queries/min per key. Slow down and retry.",
            reason=ADMISSION_REASON_RATE_LIMIT,
        )

    within_quota = await quota_repo.check_and_increment_key(key_id, limit=rag.mcp_max_queries_per_key_per_day)
    if not within_quota:
        raise QueryAdmissionError(
            f"Daily query quota exceeded: max {rag.mcp_max_queries_per_key_per_day} queries/day per key. Try again tomorrow (UTC).",
            reason=ADMISSION_REASON_DAILY_QUOTA,
        )


async def enforce_anonymous_admission(anon_key_id: str, *, quota_repo: DailyQueryQuotaRepository) -> None:
    """Enforce the anonymous (keyless) lane's admission stack. Raise on rejection.

    Cheapest first, all BEFORE any owner-paid embedding call:
      1. In-process per-IP sliding-window rate limit (no DB round-trip).
      2. Per-IP daily quota (Mongo-backed, atomic; keyed by the hashed-IP id).
      3. Anonymous global daily breaker (single sentinel row across all IPs).

    Rejection messages point at the free key-issuance page since a key unlocks
    the higher per-key tier.
    """
    rag = get_settings().rag

    if not _get_anon_rate_limiter().allow(anon_key_id):
        raise QueryAdmissionError(
            f"Rate limit exceeded: max {rag.mcp_anon_query_rate_per_min} queries/min for keyless access. Slow down and retry. {_key_signup_hint()}",
            reason=ADMISSION_REASON_RATE_LIMIT,
        )

    within_ip_quota = await quota_repo.check_and_increment_key(anon_key_id, limit=rag.mcp_anon_max_queries_per_ip_per_day)
    if not within_ip_quota:
        raise QueryAdmissionError(
            f"Daily keyless quota exceeded: max {rag.mcp_anon_max_queries_per_ip_per_day} queries/day per IP. Try again tomorrow (UTC). {_key_signup_hint()}",
            reason=ADMISSION_REASON_DAILY_QUOTA,
        )

    within_anon_global = await quota_repo.check_and_increment_key(RAG_GLOBAL_ANON_QUOTA_KEY_ID, limit=rag.mcp_anon_global_daily_max)
    if not within_anon_global:
        raise QueryAdmissionError(
            f"Keyless capacity for today is exhausted (global daily cap). Try again tomorrow (UTC). {_key_signup_hint()}",
            reason=RAG_REJECT_REASON_ANON_GLOBAL_BREAKER,
        )


def _reset_for_tests() -> None:
    """Drop the cached rate limiters so a test can rebuild them from patched settings."""
    global _rate_limiter, _anon_rate_limiter
    _rate_limiter = None
    _anon_rate_limiter = None
