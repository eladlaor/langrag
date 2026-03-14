"""Observability module for LangRAG newsletter system.

This module provides comprehensive observability capabilities:

Submodules:
- llm: LLM-specific tracing via Langfuse (costs, latency, evaluations)
- app: Application logging via loguru (JSON format, Loki integration)

Usage:
    # LLM tracing
    from observability.llm import get_langfuse_client, langfuse_span

    # Application logging
    from observability.app import get_logger, bind_context, setup_logging
"""

# Re-export commonly used items for convenience
from observability.llm import (
    # Client functions
    get_langfuse_client,
    is_langfuse_enabled,
    flush_langfuse,
    get_langfuse_callback_handler,
    shutdown_langfuse,
    # Span management
    langfuse_span,
    create_span,
    end_span_safely,
    # Trace context
    TraceContext,
    create_trace_context,
    extract_trace_context,
    # Evaluation
    score_newsletter_structure,
    score_ranking_coverage,
    score_content_balance,
    score_newsletter_generation,
    ScoringConfig,
    ScoringResult,
    ContentBalanceConfig,
)

from observability.app import (
    # Core logging
    setup_logging,
    get_logger,
    logger,
    # Context management
    bind_context,
    bind_langfuse_trace,
    bind_workflow_context,
    bind_node_context,
)

__all__ = [
    # LLM Tracing
    "get_langfuse_client",
    "is_langfuse_enabled",
    "flush_langfuse",
    "get_langfuse_callback_handler",
    "shutdown_langfuse",
    "langfuse_span",
    "create_span",
    "end_span_safely",
    "TraceContext",
    "create_trace_context",
    "extract_trace_context",
    "score_newsletter_structure",
    "score_ranking_coverage",
    "score_content_balance",
    "score_newsletter_generation",
    "ScoringConfig",
    "ScoringResult",
    "ContentBalanceConfig",
    # Application Logging
    "setup_logging",
    "get_logger",
    "logger",
    "bind_context",
    "bind_langfuse_trace",
    "bind_workflow_context",
    "bind_node_context",
]
