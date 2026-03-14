"""Prometheus metrics client for LangGraph workflow tracking.

This module provides a singleton Prometheus metrics client with:
- Node execution duration (histogram with percentiles)
- Node invocation count (counter)
- Node failure tracking (counter)
- Parallel worker metrics (gauges)

All metric recording includes fail-soft error handling to ensure
workflow execution continues even if metrics collection fails.

Usage:
    from observability.metrics import get_metrics_client, with_metrics

    # Using decorator
    @with_metrics(node_name="extract_messages", workflow_name="newsletter_generation")
    def extract_messages(state):
        ...

    # Using client directly
    metrics_client = get_metrics_client()
    with metrics_client.track_node_execution("node_name", "workflow_name"):
        # Your code here
        pass
"""

import time
from contextlib import contextmanager
from functools import lru_cache, wraps
from collections.abc import Callable

from prometheus_client import Histogram, Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

from observability.app import get_logger

logger = get_logger(__name__)


class PrometheusMetricsClient:
    """Thread-safe singleton Prometheus metrics client for LangGraph workflows.

    Provides metrics for:
    - Node execution duration (histogram)
    - Node invocation count (counter)
    - Node failures (counter)
    - Parallel worker tracking (gauges)

    All metric recording is wrapped in try-except blocks for fail-soft behavior.
    """

    def __init__(self):
        """Initialize Prometheus metrics.

        Metrics are registered on first client instantiation.
        Subsequent calls to get_metrics_client() return the same instance.
        """
        logger.info("Initializing Prometheus metrics client")

        try:
            # Node execution duration (histogram)
            # Buckets: 1s, 5s, 10s, 30s, 1m, 2m, 5m, +Inf
            self.node_duration = Histogram(name="langgraph_node_duration_seconds", documentation="Duration of LangGraph node execution in seconds", labelnames=["node_name", "workflow_name", "status"], buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, float("inf")])

            # Node invocation count
            self.node_invocations = Counter(name="langgraph_node_invocations_total", documentation="Total number of LangGraph node invocations", labelnames=["node_name", "workflow_name", "status"])

            # Node failures
            self.node_failures = Counter(name="langgraph_node_failures_total", documentation="Total number of LangGraph node failures", labelnames=["node_name", "workflow_name", "error_type"])

            # Parallel worker tracking
            self.parallel_workers_active = Gauge(name="langgraph_parallel_workers_active", documentation="Number of active parallel workers", labelnames=["workflow_name"])

            self.parallel_queue_depth = Gauge(name="langgraph_parallel_queue_depth", documentation="Number of tasks in parallel execution queue", labelnames=["workflow_name"])

            logger.info("Prometheus metrics client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Prometheus metrics client: {e}")
            raise

    @contextmanager
    def track_node_execution(self, node_name: str, workflow_name: str):
        """Context manager for tracking node execution with fail-soft error handling.

        Args:
            node_name: Name of the LangGraph node (e.g., "extract_messages")
            workflow_name: Name of the workflow (e.g., "newsletter_generation")

        Yields:
            None

        Example:
            metrics_client = get_metrics_client()
            with metrics_client.track_node_execution("extract_messages", "newsletter_generation"):
                # Your node logic here
                result = extract_messages_logic()

        Notes:
            - Records duration, invocation count, and failures
            - All metric recording is fail-soft (exceptions logged but not raised)
            - Original exceptions from node execution are re-raised
        """
        start_time = time.perf_counter()
        status = "success"

        try:
            yield
        except Exception as e:
            status = "failure"
            # Record failure (fail-soft: don't break workflow)
            try:
                self.node_failures.labels(node_name=node_name, workflow_name=workflow_name, error_type=type(e).__name__).inc()
                logger.debug(f"Recorded failure metric for node={node_name}, workflow={workflow_name}, error_type={type(e).__name__}")
            except Exception as metric_error:
                logger.warning(f"Failed to record node failure metric: {metric_error}")

            # Re-raise original exception (fail-fast workflow behavior)
            raise
        finally:
            duration = time.perf_counter() - start_time

            # Record duration and count (fail-soft)
            try:
                self.node_duration.labels(node_name=node_name, workflow_name=workflow_name, status=status).observe(duration)

                self.node_invocations.labels(node_name=node_name, workflow_name=workflow_name, status=status).inc()

                logger.debug(f"Recorded metrics for node={node_name}, workflow={workflow_name}, duration={duration:.2f}s, status={status}")
            except Exception as metric_error:
                logger.warning(f"Failed to record node metrics: {metric_error}")

    def track_parallel_workers(self, workflow_name: str, active_count: int, queue_depth: int):
        """Track parallel worker pool metrics.

        Args:
            workflow_name: Name of the workflow (e.g., "parallel_orchestrator")
            active_count: Number of currently active workers
            queue_depth: Number of tasks waiting in queue

        Example:
            metrics_client = get_metrics_client()
            metrics_client.track_parallel_workers(
                workflow_name="parallel_orchestrator",
                active_count=5,
                queue_depth=10
            )

        Notes:
            - Fail-soft: Exceptions logged but not raised
        """
        try:
            self.parallel_workers_active.labels(workflow_name=workflow_name).set(active_count)
            self.parallel_queue_depth.labels(workflow_name=workflow_name).set(queue_depth)
            logger.debug(f"Tracked parallel workers: workflow={workflow_name}, active={active_count}, queue_depth={queue_depth}")
        except Exception as e:
            logger.warning(f"Failed to track parallel worker metrics: {e}")

    def get_metrics_export(self) -> bytes:
        """Get Prometheus-formatted metrics for /metrics endpoint.

        Returns:
            bytes: Metrics in Prometheus text exposition format

        Example:
            metrics_client = get_metrics_client()
            metrics_data = metrics_client.get_metrics_export()
        """
        try:
            return generate_latest()
        except Exception as e:
            logger.error(f"Failed to generate metrics export: {e}")
            return b""

    def get_metrics_content_type(self) -> str:
        """Get content type for metrics endpoint.

        Returns:
            str: Prometheus metrics content type

        Example:
            metrics_client = get_metrics_client()
            content_type = metrics_client.get_metrics_content_type()
        """
        return CONTENT_TYPE_LATEST


@lru_cache(maxsize=1)
def get_metrics_client() -> PrometheusMetricsClient:
    """Get singleton metrics client instance.

    Returns:
        PrometheusMetricsClient: Singleton instance

    Example:
        metrics_client = get_metrics_client()
        with metrics_client.track_node_execution("node_name", "workflow_name"):
            ...

    Notes:
        - Thread-safe singleton pattern using functools.lru_cache
        - First call instantiates the client
        - Subsequent calls return the same instance
    """
    return PrometheusMetricsClient()


def with_metrics(node_name: str | None = None, workflow_name: str = "unknown"):
    """Decorator to track LangGraph node execution metrics.

    Args:
        node_name: Name of the node (defaults to function name if not provided)
        workflow_name: Name of the workflow (e.g., "newsletter_generation", "parallel_orchestrator")

    Returns:
        Callable: Decorated function

    Usage:
        @with_logging
        @with_progress(STAGE_EXTRACT, ...)
        @with_metrics(node_name="extract_messages", workflow_name="newsletter_generation")
        @with_cache_check(...)
        def extract_messages(state: SingleChatState) -> dict:
            ...

    Notes:
        - Should be placed AFTER @with_progress and BEFORE @with_cache_check
        - Tracks actual execution time (after cache check)
        - Fail-soft: Metrics failures don't break workflow execution
        - Preserves function signature and docstring via functools.wraps
        - Supports both sync and async functions (dual-mode for LangGraph 1.0)
    """

    def decorator(func: Callable) -> Callable:
        import asyncio

        effective_node_name = node_name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                metrics_client = get_metrics_client()

                # Track execution with fail-soft error handling
                with metrics_client.track_node_execution(node_name=effective_node_name, workflow_name=workflow_name):
                    result = await func(*args, **kwargs)

                return result

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                metrics_client = get_metrics_client()

                # Track execution with fail-soft error handling
                with metrics_client.track_node_execution(node_name=effective_node_name, workflow_name=workflow_name):
                    result = func(*args, **kwargs)

                return result

            return sync_wrapper

    return decorator
