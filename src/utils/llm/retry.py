"""
Retry utilities for LLM API calls with exponential backoff.

Provides decorators for retrying both sync and async functions
with configurable retry logic for transient LLM provider API failures.
Supports OpenAI, Anthropic, and Gemini exceptions dynamically.
"""

import asyncio
import logging
import random
import time
from functools import lru_cache, wraps
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds

# Generic retryable exceptions (always retry these)
_GENERIC_RETRYABLE: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
)


@lru_cache(maxsize=1)
def _get_retryable_exceptions() -> tuple[type[Exception], ...]:
    """Collect retryable exceptions from all available providers.

    Dynamically loads provider-specific exception types so that only
    installed SDKs contribute to the retry tuple.
    """
    exceptions: list[type[Exception]] = list(_GENERIC_RETRYABLE)

    try:
        import openai

        exceptions.extend(
            [
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.InternalServerError,
            ]
        )
    except ImportError:
        pass

    try:
        import anthropic

        exceptions.extend(
            [
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ]
        )
    except ImportError:
        pass

    try:
        from google.api_core import exceptions as google_exceptions

        exceptions.extend(
            [
                google_exceptions.ResourceExhausted,
                google_exceptions.ServiceUnavailable,
                google_exceptions.DeadlineExceeded,
            ]
        )
    except ImportError:
        pass

    return tuple(exceptions)


# Default retryable exceptions — evaluated once on first use
RETRYABLE_EXCEPTIONS = _get_retryable_exceptions()


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
):
    """
    Decorator for retrying functions with exponential backoff.

    Supports both sync and async functions. Uses exponential backoff
    with jitter to avoid thundering herd problems.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        retryable_exceptions: Tuple of exception types to retry (default: all provider exceptions)

    Usage:
        @with_retry(max_retries=3)
        def call_llm(prompt: str) -> str:
            ...

        @with_retry(max_retries=3)
        async def call_llm_async(prompt: str) -> str:
            ...
    """
    if retryable_exceptions is None:
        retryable_exceptions = _get_retryable_exceptions()

    def decorator(func: Callable):
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception = None

                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except retryable_exceptions as e:
                        last_exception = e

                        if attempt == max_retries:
                            logger.error(f"[{func.__name__}] All {max_retries} retries exhausted. " f"Last error: {e}")
                            raise

                        # Exponential backoff with jitter
                        delay = min(base_delay * (2**attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.1)
                        sleep_time = delay + jitter

                        logger.warning(f"[{func.__name__}] Attempt {attempt + 1}/{max_retries + 1} failed: {e}. " f"Retrying in {sleep_time:.2f}s...")

                        await asyncio.sleep(sleep_time)

                raise last_exception

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_exception = None

                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except retryable_exceptions as e:
                        last_exception = e

                        if attempt == max_retries:
                            logger.error(f"[{func.__name__}] All {max_retries} retries exhausted. " f"Last error: {e}")
                            raise

                        # Exponential backoff with jitter
                        delay = min(base_delay * (2**attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.1)
                        sleep_time = delay + jitter

                        logger.warning(f"[{func.__name__}] Attempt {attempt + 1}/{max_retries + 1} failed: {e}. " f"Retrying in {sleep_time:.2f}s...")

                        time.sleep(sleep_time)

                raise last_exception

            return sync_wrapper

    return decorator
