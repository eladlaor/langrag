"""
Unit tests for LLM retry utilities.
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock

import openai

from utils.llm.retry import (
    with_retry,
    RETRYABLE_EXCEPTIONS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_BASE_DELAY,
)


class TestWithRetrySync:
    """Tests for synchronous retry decorator."""

    def test_successful_call_no_retry(self):
        """Function succeeds on first call - no retry needed."""
        call_count = 0

        @with_retry(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()

        assert result == "success"
        assert call_count == 1

    def test_retry_on_rate_limit_error(self):
        """Function retries on RateLimitError and succeeds."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise openai.RateLimitError(
                    message="Rate limit exceeded",
                    response=Mock(status_code=429),
                    body={}
                )
            return "success"

        result = flaky_func()

        assert result == "success"
        assert call_count == 2

    def test_exhaust_retries_raises(self):
        """Function raises after exhausting all retries."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise openai.RateLimitError(
                message="Rate limit exceeded",
                response=Mock(status_code=429),
                body={}
            )

        with pytest.raises(openai.RateLimitError):
            always_fails()

        # Initial call + 2 retries = 3 total calls
        assert call_count == 3

    def test_non_retryable_exception_not_retried(self):
        """Non-retryable exceptions are raised immediately."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")

        with pytest.raises(ValueError, match="Invalid input"):
            raises_value_error()

        assert call_count == 1  # No retries for ValueError


class TestWithRetryAsync:
    """Tests for async retry decorator."""

    @pytest.mark.asyncio
    async def test_async_successful_call(self):
        """Async function succeeds on first call."""
        call_count = 0

        @with_retry(max_retries=3)
        async def async_func():
            nonlocal call_count
            call_count += 1
            return "async success"

        result = await async_func()

        assert result == "async success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_on_timeout(self):
        """Async function retries on APITimeoutError."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def flaky_async():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise openai.APITimeoutError(request=Mock())
            return "recovered"

        result = await flaky_async()

        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_exhaust_retries(self):
        """Async function raises after exhausting retries."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def always_fails_async():
            nonlocal call_count
            call_count += 1
            raise openai.APIConnectionError(request=Mock())

        with pytest.raises(openai.APIConnectionError):
            await always_fails_async()

        assert call_count == 3


class TestRetryableExceptions:
    """Tests for retryable exception configuration."""

    def test_retryable_exceptions_defined(self):
        """Verify expected exceptions are in RETRYABLE_EXCEPTIONS."""
        assert openai.RateLimitError in RETRYABLE_EXCEPTIONS
        assert openai.APITimeoutError in RETRYABLE_EXCEPTIONS
        assert openai.APIConnectionError in RETRYABLE_EXCEPTIONS
        assert openai.InternalServerError in RETRYABLE_EXCEPTIONS

    def test_defaults_are_reasonable(self):
        """Verify default values are sensible."""
        assert DEFAULT_MAX_RETRIES == 3
        assert DEFAULT_BASE_DELAY == 1.0
