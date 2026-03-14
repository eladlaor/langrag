"""Metrics API endpoint for Prometheus scraping.

This module provides the /metrics endpoint that Prometheus scrapes
to collect LangGraph node execution metrics.

Endpoint: GET /metrics
Returns: Prometheus text exposition format metrics

The endpoint is scraped by Prometheus every 10 seconds (configured in prometheus.yml).
"""

from fastapi import APIRouter, Response
from observability.metrics import get_metrics_client
from observability.app import get_logger
from constants import ROUTE_METRICS

logger = get_logger(__name__)
router = APIRouter()


@router.get(ROUTE_METRICS)
async def metrics():
    """Prometheus metrics endpoint.

    Returns metrics in Prometheus text exposition format.
    Scraped by Prometheus every 10 seconds (configured in prometheus.yml).

    Returns:
        Response: Prometheus-formatted metrics with appropriate content-type

    Metrics exposed:
        - langgraph_node_duration_seconds: Node execution duration histogram
        - langgraph_node_invocations_total: Node invocation counter
        - langgraph_node_failures_total: Node failure counter
        - langgraph_parallel_workers_active: Active parallel workers gauge
        - langgraph_parallel_queue_depth: Parallel queue depth gauge

    Example:
        curl http://localhost:8000/metrics

    Notes:
        - Fail-soft: Returns empty response if metrics export fails
        - No authentication required (internal network only)
        - Not included in OpenAPI docs by default
    """
    try:
        metrics_client = get_metrics_client()
        content = metrics_client.get_metrics_export()
        content_type = metrics_client.get_metrics_content_type()

        return Response(content=content, media_type=content_type)
    except Exception as e:
        logger.error(f"Failed to export metrics: {e}")
        # Return empty metrics on failure (fail-soft)
        return Response(content=b"", media_type="text/plain")
