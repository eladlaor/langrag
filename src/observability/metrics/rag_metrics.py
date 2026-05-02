"""
RAG-specific Prometheus metrics.

Lazy-initialised so importing the module never registers metrics that aren't
needed (and so unit tests don't fight a global registry). The retrieval
pipeline calls record_retrieval(); the eval gate calls record_eval_score().
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger(__name__)

_singleton: "_RAGMetrics | None" = None


class _RAGMetrics:
    """Holds the Prometheus instruments. One instance per process."""

    def __init__(self) -> None:
        from prometheus_client import Counter, Gauge, Histogram

        self.queries_total = Counter(
            "rag_queries_total",
            "Total RAG retrieval calls",
            ["source_filter", "date_filter_used"],
        )
        self.retrieval_latency = Histogram(
            "rag_retrieval_latency_seconds",
            "Wall time of the full retrieve()->rerank pipeline",
            ["source_filter", "date_filter_used"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, float("inf")),
        )
        self.results_returned = Histogram(
            "rag_results_returned",
            "Number of reranked chunks returned",
            ["source_filter", "date_filter_used"],
            buckets=(0, 1, 3, 5, 10, 20, float("inf")),
        )
        self.freshness_warnings = Counter(
            "rag_freshness_warnings_total",
            "Times retrieval surfaced a stale-content warning",
            ["source_filter"],
        )
        self.eval_score = Gauge(
            "rag_eval_score",
            "Last observed RAG eval score (0..1) per metric",
            ["metric"],
        )


def _get() -> _RAGMetrics | None:
    global _singleton
    if _singleton is None:
        try:
            _singleton = _RAGMetrics()
        except Exception as e:  # noqa: BLE001
            # Prometheus registry collisions or missing client. Fail-soft: metrics
            # are observability, not a correctness boundary.
            logger.warning(f"RAG metrics disabled: {e}")
            _singleton = None
    return _singleton


@contextmanager
def track_retrieval(source_filter: str, date_filter_used: bool):
    """Context manager that records a queries_total + retrieval_latency entry."""
    start = perf_counter()
    metrics = _get()
    yield
    if metrics is None:
        return
    elapsed = perf_counter() - start
    metrics.queries_total.labels(source_filter, str(date_filter_used).lower()).inc()
    metrics.retrieval_latency.labels(source_filter, str(date_filter_used).lower()).observe(elapsed)


def record_results(source_filter: str, date_filter_used: bool, count: int) -> None:
    metrics = _get()
    if metrics is None:
        return
    metrics.results_returned.labels(source_filter, str(date_filter_used).lower()).observe(count)


def record_freshness_warning(source_filter: str) -> None:
    metrics = _get()
    if metrics is None:
        return
    metrics.freshness_warnings.labels(source_filter).inc()


def record_eval_score(metric_name: str, score: float) -> None:
    metrics = _get()
    if metrics is None:
        return
    metrics.eval_score.labels(metric_name).set(score)
