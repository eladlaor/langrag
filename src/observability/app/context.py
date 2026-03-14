"""
Logging Context Management

This module provides utilities for binding contextual data to logs:
- trace_id: Correlation with Langfuse LLM traces
- run_id: Workflow/request identifier
- node_name: Current LangGraph node

Uses contextvars for thread-safe context propagation.

Usage:
    from observability.app import bind_context, get_logger

    logger = get_logger(__name__)

    # Context manager style (recommended)
    with bind_context(trace_id="abc123", run_id="workflow_1"):
        logger.info("Request received")  # Includes trace_id, run_id

        with bind_context(node_name="extract_messages"):
            logger.info("Extracting")  # Includes all three

    # Direct binding (for module-level loggers)
    logger = logger.bind(trace_id="abc123")
    logger.info("Bound logger")
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from collections.abc import Generator

from loguru import logger


# ============================================================================
# CONTEXT VARIABLES
# ============================================================================

# Thread-safe context storage
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_node_name: ContextVar[str | None] = ContextVar("node_name", default=None)


def get_current_context() -> dict[str, str | None]:
    """Get the current logging context."""
    return {
        "trace_id": _trace_id.get(),
        "run_id": _run_id.get(),
        "node_name": _node_name.get(),
    }


def set_trace_id(trace_id: str | None) -> None:
    """Set the trace_id in context."""
    _trace_id.set(trace_id)


def set_run_id(run_id: str | None) -> None:
    """Set the run_id in context."""
    _run_id.set(run_id)


def set_node_name(node_name: str | None) -> None:
    """Set the node_name in context."""
    _node_name.set(node_name)


def clear_context() -> None:
    """Clear all context variables."""
    _trace_id.set(None)
    _run_id.set(None)
    _node_name.set(None)


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


@contextmanager
def bind_context(
    trace_id: str | None = None,
    run_id: str | None = None,
    node_name: str | None = None,
    **extra: Any,
) -> Generator[None, None, None]:
    """
    Context manager for binding logging context.

    Automatically restores previous context on exit. Context values are
    additive - inner contexts inherit outer values unless explicitly overridden.

    Args:
        trace_id: Langfuse trace ID for LLM tracing correlation
        run_id: Workflow/request identifier
        node_name: Current LangGraph node name
        **extra: Additional key-value pairs to bind

    Yields:
        None (context is automatically applied to all logs within the block)

    Example:
        with bind_context(trace_id="abc123", run_id="workflow_1"):
            logger.info("Outer context")

            with bind_context(node_name="extract"):
                logger.info("Inner context")  # Has all three fields

            logger.info("Back to outer")  # Has trace_id, run_id
    """
    # Save previous values
    old_trace_id = _trace_id.get()
    old_run_id = _run_id.get()
    old_node_name = _node_name.get()

    # Set new values (inherit from parent if not specified)
    new_trace_id = trace_id if trace_id is not None else old_trace_id
    new_run_id = run_id if run_id is not None else old_run_id
    new_node_name = node_name if node_name is not None else old_node_name

    _trace_id.set(new_trace_id)
    _run_id.set(new_run_id)
    _node_name.set(new_node_name)

    # Build context dict for loguru bind
    context = {
        k: v
        for k, v in {
            "trace_id": new_trace_id,
            "run_id": new_run_id,
            "node_name": new_node_name,
            **extra,
        }.items()
        if v is not None
    }

    # Apply context to loguru
    with logger.contextualize(**context):
        try:
            yield
        finally:
            # Restore previous values
            _trace_id.set(old_trace_id)
            _run_id.set(old_run_id)
            _node_name.set(old_node_name)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def bind_langfuse_trace(trace_id: str, session_id: str | None = None) -> None:
    """
    Bind Langfuse trace context for correlation.

    Call this at the start of a request/workflow after creating a Langfuse trace.

    Args:
        trace_id: The Langfuse trace ID
        session_id: Optional session ID (often same as run_id)

    Example:
        trace = langfuse.trace(name="newsletter_generation")
        bind_langfuse_trace(trace.id, session_id=thread_id)
    """
    set_trace_id(trace_id)
    if session_id:
        set_run_id(session_id)


def bind_workflow_context(
    run_id: str,
    trace_id: str | None = None,
) -> None:
    """
    Bind workflow context at the start of a workflow.

    Args:
        run_id: Unique workflow run identifier
        trace_id: Optional Langfuse trace ID

    Example:
        thread_id = f"newsletter_{data_source}_{start_date}_{end_date}"
        bind_workflow_context(run_id=thread_id, trace_id=trace.id)
    """
    set_run_id(run_id)
    if trace_id:
        set_trace_id(trace_id)


def bind_node_context(node_name: str) -> None:
    """
    Bind the current LangGraph node name.

    Call this at the start of each graph node.

    Args:
        node_name: Name of the current node

    Example:
        def extract_messages(state: State) -> dict:
            bind_node_context("extract_messages")
            logger.info("Starting extraction")
            ...
    """
    set_node_name(node_name)
