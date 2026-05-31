"""Agentic chatbot Prometheus metrics.

Lazy-initialised so importing this module never registers metrics that
aren't needed. The tool node calls `record_tool_call`; the budget node
calls `record_budget_halt`; the memory extractor calls
`record_memory_write`; the ACL helpers call `record_acl_denial`.

The instrument set mirrors plan §I:
  - agent_tool_calls_total{tool, status}
  - agent_session_duration_seconds (histogram)
  - agent_memory_writes_total{namespace}
  - agent_budget_halts_total{reason}
  - agent_acl_denials_total{tool, community}
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger(__name__)

_singleton: "_AgentMetrics | None" = None


class _AgentMetrics:
    """Holds the agent-layer Prometheus instruments. One instance per process."""

    def __init__(self) -> None:
        from prometheus_client import Counter, Histogram

        self.tool_calls_total = Counter(
            "agent_tool_calls_total",
            "Total agent tool invocations",
            ["tool", "status"],
        )
        self.session_duration_seconds = Histogram(
            "agent_session_duration_seconds",
            "Wall-clock duration of one agent turn",
            buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
        )
        self.memory_writes_total = Counter(
            "agent_memory_writes_total",
            "Long-term memories persisted by the extractor",
            ["namespace"],
        )
        self.budget_halts_total = Counter(
            "agent_budget_halts_total",
            "Agent turns halted by the budget node",
            ["reason"],
        )
        self.acl_denials_total = Counter(
            "agent_acl_denials_total",
            "Tool invocations rejected by the per-community ACL",
            ["tool", "community"],
        )


def _get() -> _AgentMetrics:
    global _singleton
    if _singleton is None:
        try:
            _singleton = _AgentMetrics()
        except Exception as e:
            # Prometheus client unavailable or already-registered metrics.
            # Best-effort observability must never block the agent runtime.
            logger.warning("agent metrics initialization failed: %s", e)
            raise
    return _singleton


def record_tool_call(tool: str, status: str) -> None:
    """Increment `agent_tool_calls_total{tool, status}`."""
    try:
        _get().tool_calls_total.labels(tool=tool, status=status).inc()
    except Exception as e:
        logger.debug("record_tool_call failed: %s", e)


def record_memory_write(namespace: str) -> None:
    try:
        _get().memory_writes_total.labels(namespace=namespace).inc()
    except Exception as e:
        logger.debug("record_memory_write failed: %s", e)


def record_budget_halt(reason: str) -> None:
    try:
        _get().budget_halts_total.labels(reason=reason).inc()
    except Exception as e:
        logger.debug("record_budget_halt failed: %s", e)


def record_acl_denial(tool: str, community: str) -> None:
    try:
        _get().acl_denials_total.labels(tool=tool, community=community).inc()
    except Exception as e:
        logger.debug("record_acl_denial failed: %s", e)


@contextmanager
def track_session_duration():
    """Context manager wrapping one agent turn for the duration histogram."""
    start = perf_counter()
    try:
        yield
    finally:
        try:
            _get().session_duration_seconds.observe(perf_counter() - start)
        except Exception as e:
            logger.debug("session_duration observation failed: %s", e)


def reset_for_tests() -> None:
    """Drop the cached singleton (and its Prometheus instruments).

    Test-only helper: every test that checks counter labels needs a
    fresh instrument set, because the default Prometheus registry is
    process-global and the second instantiation raises 'Duplicated
    timeseries' otherwise.
    """
    global _singleton
    if _singleton is None:
        return
    try:
        from prometheus_client import REGISTRY

        for inst in (
            _singleton.tool_calls_total,
            _singleton.session_duration_seconds,
            _singleton.memory_writes_total,
            _singleton.budget_halts_total,
            _singleton.acl_denials_total,
        ):
            try:
                REGISTRY.unregister(inst)
            except Exception:
                pass
    finally:
        _singleton = None
