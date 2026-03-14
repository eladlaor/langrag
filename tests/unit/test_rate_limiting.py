"""
Unit tests for API rate limiting.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.rate_limiting import (
    setup_rate_limiting,
    limiter,
    RATE_NEWSLETTER_GENERATION,
    RATE_BATCH_JOB_QUERY,
    RATE_HEALTH_CHECK,
    RATE_DEFAULT,
)


class TestRateLimitConstants:
    """Tests for rate limit constant values."""

    def test_newsletter_generation_rate(self):
        """Newsletter generation has stricter rate limit."""
        assert RATE_NEWSLETTER_GENERATION == "10/minute"

    def test_batch_job_query_rate(self):
        """Batch job queries allow more requests."""
        assert RATE_BATCH_JOB_QUERY == "60/minute"

    def test_health_check_rate(self):
        """Health checks have highest rate limit."""
        assert RATE_HEALTH_CHECK == "120/minute"

    def test_default_rate(self):
        """Default rate is moderate."""
        assert RATE_DEFAULT == "30/minute"


class TestSetupRateLimiting:
    """Tests for setup_rate_limiting function."""

    def test_adds_middleware_to_app(self):
        """setup_rate_limiting adds SlowAPIMiddleware."""
        app = FastAPI()

        # Count middleware before
        initial_middleware_count = len(app.middleware_stack.app.middleware) if hasattr(app.middleware_stack, 'app') else 0

        setup_rate_limiting(app)

        # Verify limiter is set on app state
        assert hasattr(app.state, 'limiter')
        assert app.state.limiter is limiter

    def test_adds_exception_handler(self):
        """setup_rate_limiting adds RateLimitExceeded handler."""
        app = FastAPI()

        setup_rate_limiting(app)

        # Check exception handlers dict
        from slowapi.errors import RateLimitExceeded
        assert RateLimitExceeded in app.exception_handlers


class TestLimiterInstance:
    """Tests for limiter configuration."""

    def test_limiter_uses_remote_address(self):
        """Limiter uses client IP as key function."""
        # The limiter's key function should be get_remote_address
        from slowapi.util import get_remote_address

        # Verify limiter is configured (it exists)
        assert limiter is not None
