"""Application logging module using loguru.

This module provides JSON-formatted logging with:
- Structured fields (timestamp_il, trace_id, run_id, node_name)
- Context binding for request/workflow scoped data
- InterceptHandler to capture standard library logging
- Integration with Loki for log aggregation

Usage:
    from observability.app import get_logger, bind_context, setup_logging

    # Initialize logging (call once at startup)
    setup_logging()

    # Get a logger
    logger = get_logger(__name__)
    logger.info("Processing started")

    # With context binding
    with bind_context(trace_id="abc123", run_id="workflow_1"):
        logger.info("Request received")  # Automatically includes trace_id, run_id
"""

from observability.app.logger import (
    setup_logging,
    get_logger,
    logger,
    InterceptHandler,
)
from observability.app.context import (
    bind_context,
    get_current_context,
    set_trace_id,
    set_run_id,
    set_node_name,
    clear_context,
    bind_langfuse_trace,
    bind_workflow_context,
    bind_node_context,
)

__all__ = [
    # Core logging
    "setup_logging",
    "get_logger",
    "logger",
    "InterceptHandler",
    # Context management
    "bind_context",
    "get_current_context",
    "set_trace_id",
    "set_run_id",
    "set_node_name",
    "clear_context",
    # Helper functions
    "bind_langfuse_trace",
    "bind_workflow_context",
    "bind_node_context",
]
