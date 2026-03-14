"""LLM Tracing utilities for LangRAG newsletter system.

This module provides Langfuse integration for LLM call tracing and evaluation.

Components:
- langfuse_client: Singleton client with kill switch and graceful degradation
- evaluation: Automated structural scoring (no LLM cost)
- trace_context: Data structures for trace propagation

Usage:
    from observability.llm import get_langfuse_client, is_langfuse_enabled
    from observability.llm import TraceContext, create_trace_context
"""

from observability.llm.langfuse_client import (
    get_langfuse_client,
    is_langfuse_enabled,
    flush_langfuse,
    get_langfuse_callback_handler,
    shutdown_langfuse,
    langfuse_span,
    create_span,
    end_span_safely,
)
from observability.llm.evaluation import (
    score_newsletter_structure,
    score_ranking_coverage,
    score_content_balance,
    score_newsletter_generation,
    ScoringConfig,
    ScoringResult,
    ContentBalanceConfig,
)
from observability.llm.trace_context import (
    TraceContext,
    create_trace_context,
    extract_trace_context,
)

__all__ = [
    # Client functions
    "get_langfuse_client",
    "is_langfuse_enabled",
    "flush_langfuse",
    "get_langfuse_callback_handler",
    "shutdown_langfuse",
    # Span management
    "langfuse_span",
    "create_span",
    "end_span_safely",
    # Trace context
    "TraceContext",
    "create_trace_context",
    "extract_trace_context",
    # Evaluation functions
    "score_newsletter_structure",
    "score_ranking_coverage",
    "score_content_balance",
    "score_newsletter_generation",
    # Evaluation config and types
    "ScoringConfig",
    "ScoringResult",
    "ContentBalanceConfig",
]
