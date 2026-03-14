"""
Trace context data structures for Langfuse integration.

This module provides typed data structures for passing trace context
through LangGraph workflows, ensuring consistent trace hierarchy.

Usage:
    # Create context from API request
    ctx = create_trace_context(
        trace_id=trace.id,
        session_id=thread_id,
        user_id=request.data_source_name,
    )

    # Pass through LangGraph config
    config = {"configurable": {**ctx.to_config()}}

    # Extract from config in nodes
    ctx = extract_trace_context(config)
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TraceContext:
    """
    Immutable context for Langfuse trace propagation.

    This dataclass encapsulates all trace-related information needed
    for hierarchical trace creation across LangGraph nodes.

    Attributes:
        trace_id: Root trace ID from API endpoint
        session_id: Session identifier (typically thread_id/run_id)
        user_id: User identifier (typically data_source_name)
        parent_span_id: Parent span ID for nested spans
        tags: List of tags for filtering in Langfuse UI
        metadata: Additional metadata to attach to observations

    Example:
        ctx = TraceContext(
            trace_id="trace-123",
            session_id="session-456",
            user_id="langtalks",
            tags=["newsletter", "periodic"],
        )
    """

    trace_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    parent_span_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_config(self) -> dict[str, Any]:
        """
        Convert to LangGraph configurable dict format.

        Returns:
            Dict suitable for config["configurable"]
        """
        return {
            "langfuse_trace_id": self.trace_id,
            "langfuse_session_id": self.session_id,
            "langfuse_user_id": self.user_id,
            "langfuse_parent_span_id": self.parent_span_id,
            "langfuse_tags": self.tags,
            "langfuse_metadata": self.metadata,
        }

    def to_state(self) -> dict[str, Any]:
        """
        Convert to state dict format for LangGraph state.

        Returns:
            Dict suitable for merging into graph state
        """
        return {
            "langfuse_trace_id": self.trace_id,
            "langfuse_session_id": self.session_id,
            "langfuse_user_id": self.user_id,
        }

    def with_parent_span(self, span_id: str) -> "TraceContext":
        """
        Create new context with updated parent span ID.

        Args:
            span_id: New parent span ID

        Returns:
            New TraceContext with updated parent_span_id
        """
        return TraceContext(
            trace_id=self.trace_id,
            session_id=self.session_id,
            user_id=self.user_id,
            parent_span_id=span_id,
            tags=self.tags,
            metadata=self.metadata,
        )

    def with_metadata(self, **kwargs) -> "TraceContext":
        """
        Create new context with additional metadata.

        Args:
            **kwargs: Additional metadata key-value pairs

        Returns:
            New TraceContext with merged metadata
        """
        return TraceContext(
            trace_id=self.trace_id,
            session_id=self.session_id,
            user_id=self.user_id,
            parent_span_id=self.parent_span_id,
            tags=self.tags,
            metadata={**self.metadata, **kwargs},
        )

    @property
    def is_valid(self) -> bool:
        """Check if context has a valid trace_id for creating spans."""
        return self.trace_id is not None


def create_trace_context(
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    parent_span_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceContext:
    """
    Factory function to create TraceContext with defaults.

    Args:
        trace_id: Root trace ID
        session_id: Session identifier
        user_id: User identifier
        parent_span_id: Parent span for nested spans
        tags: List of tags
        metadata: Additional metadata

    Returns:
        New TraceContext instance
    """
    return TraceContext(
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        parent_span_id=parent_span_id,
        tags=tags or [],
        metadata=metadata or {},
    )


def extract_trace_context(config: dict[str, Any] | None) -> TraceContext:
    """
    Extract TraceContext from LangGraph config.

    This is the inverse of TraceContext.to_config(), used in graph nodes
    to retrieve trace context from the config parameter.

    Args:
        config: LangGraph config dict with "configurable" key

    Returns:
        TraceContext extracted from config, or empty context if not found
    """
    if not config:
        return TraceContext()

    configurable = config.get("configurable", {})

    return TraceContext(
        trace_id=configurable.get("langfuse_trace_id"),
        session_id=configurable.get("langfuse_session_id"),
        user_id=configurable.get("langfuse_user_id"),
        parent_span_id=configurable.get("langfuse_parent_span_id"),
        tags=configurable.get("langfuse_tags", []),
        metadata=configurable.get("langfuse_metadata", {}),
    )


def extract_trace_context_from_state(state: dict[str, Any]) -> TraceContext:
    """
    Extract TraceContext from LangGraph state.

    Used when trace context is stored directly in state rather than config.

    Args:
        state: LangGraph state dict

    Returns:
        TraceContext extracted from state
    """
    return TraceContext(
        trace_id=state.get("langfuse_trace_id"),
        session_id=state.get("langfuse_session_id"),
        user_id=state.get("langfuse_user_id"),
    )
