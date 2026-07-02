"""
In-process per-key sliding-window rate limiter (COST-2).

slowapi only guards the FastAPI :8000 app. The MCP SSE app runs in a SEPARATE
uvicorn process (:8765) and is otherwise only rate-limited per-IP at nginx —
defeated by IP rotation with one valid key. This module adds an in-process,
per-key sliding-window limiter keyed on key_id so a single key cannot flood the
owner-paid embedding path regardless of source IP.

Design:
  - Per key, a deque of recent hit timestamps. On each ``allow`` call, timestamps
    older than the window are discarded; if the remaining count is below the cap
    the hit is recorded and admitted, else it is rejected.
  - The clock is injectable so the window is deterministically testable.
  - Single-process, single-event-loop asyncio: the check/record is synchronous and
    atomic with respect to the loop (no await between prune and append), so no lock
    is needed. It is a per-process limiter by construction (see the concurrency
    guard module for the same per-process rationale).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """A per-key sliding-window rate limiter with an injectable clock."""

    def __init__(
        self,
        *,
        max_per_window: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_per_window <= 0:
            raise ValueError(f"max_per_window must be positive, got {max_per_window}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be positive, got {window_seconds}")
        self._max = max_per_window
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record and admit one hit for ``key``, or reject if over the cap.

        Returns True if the hit is within the per-window budget (and records it),
        False if admitting it would exceed the cap (nothing recorded).
        """
        now = self._clock()
        cutoff = now - self._window
        bucket = self._hits[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            logger.warning(
                "Per-key MCP query rate limit hit",
                extra={"event": "mcp_rate_limited", "key_id": key, "max_per_window": self._max, "window_seconds": self._window},
            )
            return False
        bucket.append(now)
        return True

    def _reset_for_tests(self) -> None:
        """Drop all per-key state (tests only)."""
        self._hits.clear()
