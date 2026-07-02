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


def _reset_for_tests() -> None:
    """Drop the cached rate limiter so a test can rebuild it from patched settings."""
    global _rate_limiter
    _rate_limiter = None
