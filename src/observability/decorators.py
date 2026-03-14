"""
Observability decorators for graph nodes.

Provides decorators for automatic tracing context extraction
and span management to reduce boilerplate in node implementations.
"""

import asyncio
import logging
from functools import wraps
from collections.abc import Callable

from observability import langfuse_span, extract_trace_context

logger = logging.getLogger(__name__)


def with_trace_span(span_name: str | None = None, include_state_keys: list[str] | None = None):
    """
    Decorator that wraps node execution in a Langfuse span.

    Automatically extracts trace context from config and creates span
    with standardized input/output tracking. Reduces boilerplate code
    in node implementations.

    Args:
        span_name: Override span name (default: function name)
        include_state_keys: State keys to include in span input
                           (default: ["chat_name"])

    Usage:
        @with_trace_span(include_state_keys=["chat_name", "start_date"])
        async def my_node(state, config, _span=None):
            # _span is injected by decorator
            # ... node logic ...
            return result  # Automatically added to span output

        @with_trace_span()
        def my_sync_node(state, config, _span=None):
            # Works with sync functions too
            return result
    """
    if include_state_keys is None:
        include_state_keys = ["chat_name"]

    def decorator(func: Callable):
        name = span_name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(state, config=None, **kwargs):
                ctx = extract_trace_context(config)
                input_data = {k: state.get(k) for k in include_state_keys}

                with langfuse_span(name=name, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data=input_data, metadata={"source_name": state.get("data_source_name")}) as span:
                    # Inject span into kwargs if function expects it
                    result = await func(state, config, _span=span, **kwargs)
                    if span and isinstance(result, dict):
                        span.update(output=result)
                    return result

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(state, config=None, **kwargs):
                ctx = extract_trace_context(config)
                input_data = {k: state.get(k) for k in include_state_keys}

                with langfuse_span(name=name, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data=input_data, metadata={"source_name": state.get("data_source_name")}) as span:
                    # Inject span into kwargs if function expects it
                    result = func(state, config, _span=span, **kwargs)
                    if span and isinstance(result, dict):
                        span.update(output=result)
                    return result

            return sync_wrapper

    return decorator
