"""
RAG Conversation Graph Nodes

Node implementations for the retrieve -> generate -> evaluate flow.
"""

import asyncio
import logging
import random
import uuid
from typing import Any

from config import get_settings
from custom_types.field_keys import RAGChunkKeys
from graphs.rag_conversation.state import RAGConversationState
from graphs.state_keys import RAGConversationStateKeys as Keys
from rag.evaluation.runtime.scorer import score_response
from rag.evaluation.runtime.se_shadow import shadow_score_se
from rag.retrieval.pipeline import RetrievalPipeline
from constants import RAG_REFUSAL_INSUFFICIENT_EVIDENCE
from rag.generation.grounding import find_ungrounded_date_tags, is_evidence_sufficient
from rag.generation.rag_chain import generate_answer

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


async def retrieve_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Retrieve relevant chunks for the user query.

    Honours optional date_start / date_end so callers can scope retrieval to a
    window (the AI field changes fast — answers grounded in stale content can
    be misleading). Surfaces a freshness_warning when retrieved chunks are older
    than the configured threshold.
    """
    query = state[Keys.QUERY]
    content_sources = state.get(Keys.CONTENT_SOURCES) or None
    date_start = state.get(Keys.DATE_START)
    date_end = state.get(Keys.DATE_END)

    logger.info(
        f"RAG retrieve: query='{query[:80]}...', sources={content_sources}, "
        f"date_start={date_start}, date_end={date_end}"
    )

    # Resolve the caller's saved MMR preference when this node runs under a
    # bound user context. If none is bound (the rag_conversation graph is not
    # currently invoked under a user context), fall back to the config default
    # by passing nothing.
    mmr_lambda: float | None = None
    enable_mmr: bool | None = None
    try:
        from agent.auth.user_context import NoUserContextError, current_user_context
        from db.connection import get_database
        from db.repositories.users import UsersRepository

        try:
            ctx = current_user_context()
        except NoUserContextError:
            ctx = None

        if ctx is not None:
            db = await get_database()
            prefs = await UsersRepository(db).get_rag_preferences(ctx.user_id)
            mmr_lambda = prefs.mmr_lambda
            enable_mmr = prefs.enable_mmr_diversity
    except Exception as e:
        logger.error(
            "retrieve_node failed resolving rag preferences",
            extra={"event": "retrieve_node_prefs_failed", "function": "retrieve_node", "error": str(e)},
        )
        raise

    pipeline = RetrievalPipeline()
    result = await pipeline.retrieve(
        query=query,
        content_sources=content_sources,
        date_start=date_start,
        date_end=date_end,
        mmr_lambda=mmr_lambda,
        enable_mmr=enable_mmr,
    )

    return {
        Keys.RETRIEVED_CHUNKS: result["retrieved_chunks"],
        Keys.RERANKED_CHUNKS: result["reranked_chunks"],
        Keys.CONTEXT: result["context"],
        Keys.CITATIONS: result["citations"],
        Keys.FRESHNESS_WARNING: result["freshness_warning"],
        Keys.OLDEST_SOURCE_DATE: result["oldest_source_date"],
        Keys.NEWEST_SOURCE_DATE: result["newest_source_date"],
    }


async def generate_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Generate an answer using the retrieved context and conversation history.
    """
    query = state[Keys.QUERY]
    context = state.get(Keys.CONTEXT, "")
    history = state.get(Keys.CONVERSATION_HISTORY, [])

    if not context:
        date_start = state.get(Keys.DATE_START)
        date_end = state.get(Keys.DATE_END)
        if date_start or date_end:
            answer = (
                "No content was found within the requested date range. "
                "Please broaden the date window or rephrase the question."
            )
        else:
            answer = (
                "I couldn't find any relevant information in the available sources to answer your question. "
                "Could you try rephrasing or asking about a different topic?"
            )
        return {Keys.ANSWER: answer}

    # Evidence gate: refuse instead of generating when nothing retrieved is
    # strong enough to ground an answer (see rag.generation.grounding).
    citations = state.get(Keys.CITATIONS, [])
    if not is_evidence_sufficient(citations, get_settings().rag.min_answer_evidence_score):
        logger.warning(f"RAG generate: evidence below floor, refusing (query='{query[:80]}')")
        return {Keys.ANSWER: RAG_REFUSAL_INSUFFICIENT_EVIDENCE}

    logger.info(f"RAG generate: query='{query[:80]}...', context_len={len(context)}")

    answer = await generate_answer(
        query=query,
        context=context,
        conversation_history=history,
        date_start=state.get(Keys.DATE_START),
        date_end=state.get(Keys.DATE_END),
        freshness_warning=state.get(Keys.FRESHNESS_WARNING, False),
        newest_source_date=state.get(Keys.NEWEST_SOURCE_DATE),
    )

    # Date-tag grounding check: discard answers carrying date tags no citation covers.
    ungrounded_tags = find_ungrounded_date_tags(answer, citations)
    if ungrounded_tags:
        logger.error(
            "RAG generate: answer discarded — ungrounded date tags "
            f"{ungrounded_tags} not covered by any citation (query='{query[:80]}')"
        )
        return {Keys.ANSWER: RAG_REFUSAL_INSUFFICIENT_EVIDENCE}

    return {Keys.ANSWER: answer}


async def evaluate_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Conditionally fire background runtime scoring.

    The scorer dual-writes to MongoDB (rag_evaluations) and Langfuse (trace
    scores). DeepEval is no longer used at runtime; the CI eval gate keeps it.
    """
    settings = get_settings().runtime_eval

    if not settings.enabled:
        return {Keys.EVALUATION_ID: None}

    if random.random() > settings.sampling_rate:
        return {Keys.EVALUATION_ID: None}

    evaluation_id = str(uuid.uuid4())

    task = asyncio.create_task(
        _run_background_scoring(
            evaluation_id=evaluation_id,
            session_id=state[Keys.SESSION_ID],
            query=state[Keys.QUERY],
            answer=state.get(Keys.ANSWER, ""),
            contexts=[c.get(RAGChunkKeys.CONTENT, "") for c in state.get(Keys.RERANKED_CHUNKS, [])],
            langfuse_trace_id=state.get(Keys.LANGFUSE_TRACE_ID),
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(f"Background runtime scoring scheduled: evaluation_id={evaluation_id}")
    return {Keys.EVALUATION_ID: evaluation_id}


async def _run_background_scoring(
    evaluation_id: str,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
    langfuse_trace_id: str | None,
) -> None:
    """Run runtime scoring in the background. Fail-soft: never crashes the conversation."""
    try:
        await score_response(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            answer=answer,
            contexts=contexts,
            langfuse_trace_id=langfuse_trace_id,
        )
    except Exception as e:
        logger.warning(f"Background runtime scoring failed (non-blocking): evaluation_id={evaluation_id}, error={e}")

    # Independent SE shadow scoring. Returns None instantly when disabled, so
    # this is effectively free (and imports no taste/torch) when off. A shadow
    # failure cannot affect the judge write above and vice versa.
    try:
        await shadow_score_se(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            contexts=contexts,
            conversation_history=None,
            langfuse_trace_id=langfuse_trace_id,
        )
    except Exception as e:
        logger.warning(f"Background SE shadow scoring failed (non-blocking): evaluation_id={evaluation_id}, error={e}")
