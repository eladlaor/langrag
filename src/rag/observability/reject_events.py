"""
Reject observability for the RAG surface (OBS-2).

The plan wants rejects visible as an abuse detector, not just successful queries.
Today rejects land only in Loki logs; this helper additionally emits, at each
reject point:

  - a per-(reason, tool) Prometheus counter (record_reject), and
  - a lightweight Langfuse event tagged with the resolved key_id (NEVER the raw
    bearer) so per-key abuse shows up on the self-hosted Langfuse.

It is a REUSABLE helper so the code paths owned by this change (validation
rejects, the new quota/rate/breaker rejects) and the paths owned by the security
agent (auth_context/scopes rejects) can all call one function. It degrades safely
to a metric-only no-op when Langfuse is disabled, and never raises (reject
observability must not itself break a request).
"""

from __future__ import annotations

import logging

from constants import RAG_REJECT_EVENT_NAME, RAG_TRACE_META_KEY_ID
from observability.llm.langfuse_client import get_langfuse_client, is_langfuse_enabled
from observability.metrics.rag_metrics import record_reject

logger = logging.getLogger(__name__)


def emit_reject(*, reason: str, key_id: str | None, tool: str) -> None:
    """Emit a reject signal (metric + Langfuse event). Best-effort, never raises.

    Args:
        reason: A stable reason label (e.g. RAG_REJECT_REASON_SCOPE_DENIED or an
            admission reason). Becomes a Prometheus label and the event metadata.
        key_id: The resolved per-key identifier (hash/id) or None on unauthenticated
            rejects. NEVER pass the raw bearer token.
        tool: The tool/endpoint the reject occurred on (e.g. "search_podcasts").
    """
    try:
        record_reject(reason, tool)
    except Exception as e:  # noqa: BLE001 — metrics are best-effort
        logger.debug("record_reject failed", extra={"event": "reject_metric_failed", "error": str(e)})

    logger.warning(
        "RAG request rejected",
        extra={"event": RAG_REJECT_EVENT_NAME, "reason": reason, "key_id": key_id, "tool": tool},
    )

    if not is_langfuse_enabled():
        return
    try:
        client = get_langfuse_client()
        if not client:
            return
        client.event(
            name=RAG_REJECT_EVENT_NAME,
            metadata={"reason": reason, RAG_TRACE_META_KEY_ID: key_id, "tool": tool},
        )
    except Exception as e:  # noqa: BLE001 — Langfuse emission must never break a reject
        logger.debug(
            "Failed to emit reject Langfuse event",
            extra={"event": "reject_event_failed", "reason": reason, "error": str(e)},
        )
