"""
Langfuse client singleton for tracing and evaluation.

This module provides a centralized Langfuse client with:
- Kill switch via LANGFUSE_ENABLED environment variable
- Graceful degradation when not configured
- Singleton pattern for efficiency
- Context manager for automatic span lifecycle management

Environment Variables:
    LANGFUSE_ENABLED: Set to "false" to disable all tracing (default: "true")
    LANGFUSE_HOST: Langfuse server URL (required for tracing)
    LANGFUSE_PUBLIC_KEY: API public key (required for tracing)
    LANGFUSE_SECRET_KEY: API secret key (required for tracing)

Usage:
    from observability.llm import (
        get_langfuse_client,
        is_langfuse_enabled,
        langfuse_span,
    )

    # Check if enabled
    if is_langfuse_enabled():
        client = get_langfuse_client()

    # Use context manager for automatic span lifecycle
    with langfuse_span("my_operation", trace_id=trace_id) as span:
        # do work
        span.update(output={"result": "success"})
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from collections.abc import Generator

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.client import StatefulSpanClient

logger = logging.getLogger(__name__)


def is_langfuse_enabled() -> bool:
    """
    Check if Langfuse tracing is enabled (kill switch).

    Returns:
        True if LANGFUSE_ENABLED is not set or is "true" (case-insensitive).
        False if explicitly set to "false".
    """
    return os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"


@lru_cache(maxsize=1)
def _initialize_langfuse() -> tuple[Langfuse | None, Exception | None]:
    """
    Initialize Langfuse client (cached singleton).

    The client is initialized once and cached. Subsequent calls return
    the cached instance. This ensures efficient resource usage.

    Note:
        The lru_cache means environment variable changes after first
        initialization will not take effect until process restart.

    Returns:
        Tuple of (client, error) - client is None if initialization failed
    """
    # Kill switch check
    if not is_langfuse_enabled():
        logger.info("Langfuse tracing disabled via LANGFUSE_ENABLED=false")
        return None, None

    # Check if host is configured
    host = os.getenv("LANGFUSE_HOST")
    if not host:
        logger.info("LANGFUSE_HOST not configured, tracing disabled")
        return None, None

    # Check for API keys
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")

    if not secret_key or not public_key:
        logger.info("Langfuse API keys not configured, tracing disabled")
        return None, None

    try:
        from langfuse import Langfuse

        client = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=host,
        )
        logger.info(f"Langfuse client initialized successfully, host={host}")
        return client, None

    except ImportError as e:
        logger.warning(f"Langfuse package not installed: {e}")
        return None, e

    except Exception as e:
        logger.error(f"Failed to initialize Langfuse client: {e}")
        return None, e


def get_langfuse_client() -> Langfuse | None:
    """
    Get Langfuse client singleton.

    Returns None if disabled or not configured (graceful degradation).
    Safe to call even when Langfuse is not available.

    Returns:
        Langfuse client instance or None
    """
    client, _ = _initialize_langfuse()
    return client


def flush_langfuse() -> None:
    """
    Flush pending traces to Langfuse server.

    Call this at the end of request handlers to ensure all traces are sent.
    Safe to call even if Langfuse is disabled.
    """
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse traces: {e}")


def shutdown_langfuse() -> None:
    """
    Shutdown Langfuse client gracefully.

    Call this on application shutdown to ensure all pending traces are sent
    and resources are released. Safe to call even if Langfuse is disabled.
    """
    client = get_langfuse_client()
    if client:
        try:
            client.shutdown()
            logger.info("Langfuse client shutdown complete")
        except Exception as e:
            logger.warning(f"Failed to shutdown Langfuse client: {e}")


def get_langfuse_callback_handler(
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
):
    """
    Get a LangChain callback handler for Langfuse tracing.

    This is used for tracing LangChain/LangGraph operations that use
    the callback system (e.g., ChatOpenAI, chains).

    Args:
        trace_id: Existing trace ID to attach to (for hierarchical traces)
        session_id: Session ID for grouping related traces
        user_id: User identifier (e.g., data_source_name)
        tags: List of tags for filtering in Langfuse UI
        metadata: Additional metadata to attach to the trace

    Returns:
        CallbackHandler instance or None if Langfuse is disabled/unavailable
    """
    if not is_langfuse_enabled():
        return None

    client = get_langfuse_client()
    if not client:
        return None

    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            tags=tags or [],
            metadata=metadata or {},
        )
    except ImportError:
        logger.warning("langfuse.callback not available")
        return None
    except Exception as e:
        logger.warning(f"Failed to create Langfuse callback handler: {e}")
        return None


@contextmanager
def langfuse_span(
    name: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    input_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[StatefulSpanClient | None, None, None]:
    """
    Context manager for creating Langfuse spans with automatic lifecycle management.

    This ensures spans are properly ended even if exceptions occur, and provides
    a clean interface for span creation in graph nodes.

    Args:
        name: Name of the span (e.g., "consolidate_discussions")
        trace_id: Root trace ID to attach to
        parent_span_id: Parent span ID for nested spans
        input_data: Input data to log with the span
        metadata: Additional metadata for the span

    Yields:
        StatefulSpanClient or None if Langfuse is disabled

    Example:
        with langfuse_span("my_operation", trace_id=trace_id) as span:
            result = do_work()
            if span:
                span.update(output={"result": result})
    """
    if not is_langfuse_enabled():
        yield None
        return

    langfuse = get_langfuse_client()
    if not langfuse or not trace_id:
        yield None
        return

    span = None
    try:
        span_kwargs: dict[str, Any] = {
            "trace_id": trace_id,
            "name": name,
        }
        if parent_span_id:
            span_kwargs["parent_observation_id"] = parent_span_id
        if input_data:
            span_kwargs["input"] = input_data
        if metadata:
            span_kwargs["metadata"] = metadata

        span = langfuse.span(**span_kwargs)
        yield span

    except Exception as e:
        logger.warning(f"Failed to create Langfuse span '{name}': {e}")
        yield None

    finally:
        if span:
            try:
                span.end()
            except Exception as e:
                logger.warning(f"Failed to end Langfuse span '{name}': {e}")


def create_span(
    name: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    input_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> StatefulSpanClient | None:
    """
    Create a Langfuse span manually (non-context-manager version).

    Use this when you need more control over span lifecycle, but remember
    to call span.end() when done. Prefer langfuse_span() context manager
    for simpler use cases.

    Args:
        name: Name of the span
        trace_id: Root trace ID to attach to
        parent_span_id: Parent span ID for nested spans
        input_data: Input data to log
        metadata: Additional metadata

    Returns:
        StatefulSpanClient or None if Langfuse is disabled
    """
    if not is_langfuse_enabled():
        return None

    langfuse = get_langfuse_client()
    if not langfuse or not trace_id:
        return None

    try:
        span_kwargs: dict[str, Any] = {
            "trace_id": trace_id,
            "name": name,
        }
        if parent_span_id:
            span_kwargs["parent_observation_id"] = parent_span_id
        if input_data:
            span_kwargs["input"] = input_data
        if metadata:
            span_kwargs["metadata"] = metadata

        return langfuse.span(**span_kwargs)

    except Exception as e:
        logger.warning(f"Failed to create Langfuse span '{name}': {e}")
        return None


def end_span_safely(
    span: StatefulSpanClient | None,
    output: dict[str, Any] | None = None,
    level: str = "DEFAULT",
    status_message: str | None = None,
) -> None:
    """
    Safely end a span with output and status.

    This helper ensures span ending doesn't raise exceptions and
    provides a consistent interface for span completion.

    Args:
        span: The span to end (can be None)
        output: Output data to attach to the span
        level: Log level ("DEFAULT", "WARNING", "ERROR")
        status_message: Status message (typically for errors)
    """
    if not span:
        return

    try:
        update_kwargs: dict[str, Any] = {"level": level}
        if output:
            update_kwargs["output"] = output
        if status_message:
            update_kwargs["status_message"] = status_message

        span.update(**update_kwargs)
        span.end()

    except Exception as e:
        logger.warning(f"Failed to end Langfuse span: {e}")
