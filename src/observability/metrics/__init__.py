"""Prometheus metrics tracking for LangGraph workflows.

This module provides:
- Prometheus metrics client for tracking node execution
- @with_metrics decorator for instrumenting nodes
- /metrics endpoint for Prometheus scraping

Usage:
    from observability.metrics import with_metrics, get_metrics_client

    # Using decorator (recommended)
    @with_metrics(node_name="extract_messages", workflow_name="newsletter_generation")
    def extract_messages(state):
        ...

    # Using client directly
    metrics_client = get_metrics_client()
    with metrics_client.track_node_execution("node_name", "workflow_name"):
        # Your code here
        pass

    # Tracking parallel workers
    metrics_client = get_metrics_client()
    metrics_client.track_parallel_workers(
        workflow_name="parallel_orchestrator",
        active_count=5,
        queue_depth=10
    )
"""

from observability.metrics.prometheus_client import (
    PrometheusMetricsClient,
    get_metrics_client,
    with_metrics,
)

__all__ = [
    "PrometheusMetricsClient",
    "get_metrics_client",
    "with_metrics",
]
