"""Unit tests for the in-process per-key sliding-window rate limiter (COST-2).

Pure logic, no Docker: a monotonic clock is injected so the window is deterministic.
"""

import pytest

from rag.quota.rate_limiter import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    def test_allows_up_to_limit_within_window(self):
        clock = {"t": 1000.0}
        limiter = SlidingWindowRateLimiter(max_per_window=3, window_seconds=60, clock=lambda: clock["t"])
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True

    def test_rejects_over_limit_within_window(self):
        clock = {"t": 1000.0}
        limiter = SlidingWindowRateLimiter(max_per_window=2, window_seconds=60, clock=lambda: clock["t"])
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is False

    def test_window_slides_and_frees_capacity(self):
        clock = {"t": 1000.0}
        limiter = SlidingWindowRateLimiter(max_per_window=2, window_seconds=60, clock=lambda: clock["t"])
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is False
        # Advance past the window: the two old hits fall out.
        clock["t"] += 61
        assert limiter.allow("k") is True

    def test_keys_are_isolated(self):
        clock = {"t": 1000.0}
        limiter = SlidingWindowRateLimiter(max_per_window=1, window_seconds=60, clock=lambda: clock["t"])
        assert limiter.allow("a") is True
        assert limiter.allow("a") is False
        # A different key has its own bucket.
        assert limiter.allow("b") is True

    def test_partial_window_slide(self):
        clock = {"t": 0.0}
        limiter = SlidingWindowRateLimiter(max_per_window=2, window_seconds=10, clock=lambda: clock["t"])
        limiter.allow("k")  # t=0
        clock["t"] = 6
        limiter.allow("k")  # t=6
        clock["t"] = 8
        assert limiter.allow("k") is False  # both still in window
        clock["t"] = 11
        # t=0 hit now expired (>10s old), t=6 still in window -> capacity for one.
        assert limiter.allow("k") is True

    def test_rejects_non_positive_config(self):
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(max_per_window=0, window_seconds=60)
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(max_per_window=1, window_seconds=0)
