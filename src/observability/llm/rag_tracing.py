"""
Live-RAG Langfuse tracing + online-eval scheduling (SRP helper).

Owns the two pieces of Langfuse plumbing for the LIVE RAG request paths
(REST rag_chat / rag_chat_stream, MCP rag_query / rag_search) so neither the
API router nor the MCP tools carry trace-creation code or a background-task set:

1. create_rag_trace(...) — a thin, guarded wrapper over `langfuse.trace(...)`
   mirroring api/newsletter_gen.py. Returns (trace, trace_id) or (None, None)
   when Langfuse is disabled/unavailable so callers degrade to today's behavior.

2. schedule_rag_online_eval(...) — the fire-and-forget online-eval scheduler
   HARVESTED from graphs/rag_conversation/nodes.py (evaluate_node +
   _run_background_scoring). It imports the scorer / SE-shadow primitives
   DIRECTLY and NEVER imports graphs.rag_conversation (that graph is orphaned;
   production never routes through it). Each scoring call is fail-soft.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime
from typing import Any

from config import get_settings
from constants import (
    RAG_TRACE_INPUT_MAX,
    RAG_TRACE_META_CONTENT_SOURCES,
    RAG_TRACE_META_DATE_END,
    RAG_TRACE_META_DATE_START,
)
from observability.llm.langfuse_client import get_langfuse_client, is_langfuse_enabled
from rag.evaluation.runtime.scorer import score_response
from rag.evaluation.runtime.se_shadow import shadow_score_se

logger = logging.getLogger(__name__)

# Module-level strong references to in-flight background eval tasks. asyncio only
# holds a weak reference to tasks, so without this set a fire-and-forget task can
# be garbage-collected mid-run. The done-callback discards each task on completion.
_online_eval_tasks: set[asyncio.Task] = set()


def _iso_or_none(value: datetime | None) -> str | None:
    """ISO-8601 date string for a datetime, or None."""
    return value.date().isoformat() if value else None


def create_rag_trace(
    *,
    name: str,
    user_id: str | None,
    session_id: str | None,
    query: str,
    content_sources: list[str] | None,
    date_start: datetime | None,
    date_end: datetime | None,
    tags: list[str],
) -> tuple[Any | None, str | None]:
    """Create one Langfuse trace for a live RAG request.

    Guarded like api/newsletter_gen.py: returns (None, None) when Langfuse is
    disabled or the client is unavailable, so the caller's happy path is a no-op
    kill-switch. The query input is truncated to RAG_TRACE_INPUT_MAX. Dates are
    serialized via .isoformat() under the RAG_TRACE_META_* metadata keys.

    Returns:
        (trace, trace.id) on success; (None, None) otherwise.
    """
    if not is_langfuse_enabled():
        return None, None

    langfuse = get_langfuse_client()
    if not langfuse:
        return None, None

    try:
        trace = langfuse.trace(
            name=str(name),
            user_id=user_id,
            session_id=session_id,
            input=query[:RAG_TRACE_INPUT_MAX],
            metadata={
                RAG_TRACE_META_CONTENT_SOURCES: content_sources or [],
                RAG_TRACE_META_DATE_START: _iso_or_none(date_start),
                RAG_TRACE_META_DATE_END: _iso_or_none(date_end),
            },
            tags=[str(t) for t in tags],
        )
        return trace, trace.id
    except Exception as e:
        logger.warning(
            "Failed to create RAG Langfuse trace",
            extra={"event": "rag_trace_create_failed", "function": "create_rag_trace", "trace_name": str(name), "error": str(e)},
        )
        return None, None


def schedule_rag_online_eval(
    *,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
    trace_id: str | None,
) -> str | None:
    """Fire-and-forget background scoring of a live RAG answer.

    Gate (all must hold): settings.rag.online_eval_enabled AND
    settings.runtime_eval.enabled AND random() <= runtime_eval.sampling_rate.
    On pass, schedules an asyncio task (held in _online_eval_tasks) that runs
    score_response then shadow_score_se, each fail-soft. Returns the generated
    evaluation_id, or None when gated out.
    """
    settings = get_settings()

    if not settings.rag.online_eval_enabled:
        return None

    runtime_eval = settings.runtime_eval
    if not runtime_eval.enabled:
        return None

    if random.random() > runtime_eval.sampling_rate:
        return None

    evaluation_id = str(uuid.uuid4())

    task = asyncio.create_task(
        _run_online_eval(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            answer=answer,
            contexts=contexts,
            trace_id=trace_id,
        )
    )
    _online_eval_tasks.add(task)
    task.add_done_callback(_online_eval_tasks.discard)

    logger.info(
        "Live RAG online eval scheduled",
        extra={"event": "rag_online_eval_scheduled", "function": "schedule_rag_online_eval", "evaluation_id": evaluation_id, "session_id": session_id, "trace_id": trace_id},
    )
    return evaluation_id


async def _run_online_eval(
    *,
    evaluation_id: str,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
    trace_id: str | None,
) -> None:
    """Run the two scorers back-to-back, each fail-soft (never re-raise)."""
    try:
        await score_response(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            answer=answer,
            contexts=contexts,
            langfuse_trace_id=trace_id,
        )
    except Exception as e:
        logger.warning(
            "Live RAG online judge scoring failed (non-blocking)",
            extra={"event": "rag_online_eval_judge_failed", "function": "_run_online_eval", "evaluation_id": evaluation_id, "error": str(e)},
        )

    # SE shadow scoring is independent: a shadow failure must not affect the judge
    # write above and vice versa. Returns instantly (no heavy imports) when off.
    try:
        await shadow_score_se(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            contexts=contexts,
            conversation_history=None,
            langfuse_trace_id=trace_id,
        )
    except Exception as e:
        logger.warning(
            "Live RAG online SE-shadow scoring failed (non-blocking)",
            extra={"event": "rag_online_eval_shadow_failed", "function": "_run_online_eval", "evaluation_id": evaluation_id, "error": str(e)},
        )
