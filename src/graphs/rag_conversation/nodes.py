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
from rag.retrieval.pipeline import RetrievalPipeline
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

    pipeline = RetrievalPipeline()
    result = await pipeline.retrieve(
        query=query,
        content_sources=content_sources,
        date_start=date_start,
        date_end=date_end,
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

    return {Keys.ANSWER: answer}


async def evaluate_node(state: RAGConversationState) -> dict[str, Any]:
    """Conditionally fire background DeepEval evaluation."""
    settings = get_settings().deepeval

    if not settings.enabled:
        return {Keys.EVALUATION_ID: None}

    if random.random() > settings.sampling_rate:
        return {Keys.EVALUATION_ID: None}

    evaluation_id = str(uuid.uuid4())

    task = asyncio.create_task(
        _run_background_evaluation(
            evaluation_id=evaluation_id,
            session_id=state[Keys.SESSION_ID],
            query=state[Keys.QUERY],
            answer=state.get(Keys.ANSWER, ""),
            contexts=[c.get(RAGChunkKeys.CONTENT, "") for c in state.get(Keys.RERANKED_CHUNKS, [])],
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(f"Background evaluation scheduled: evaluation_id={evaluation_id}")
    return {Keys.EVALUATION_ID: evaluation_id}


async def _run_background_evaluation(
    evaluation_id: str,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
) -> None:
    """Run DeepEval evaluation in the background. Fail-soft: never crashes the conversation."""
    try:
        from rag.evaluation.evaluator import run_evaluation

        await run_evaluation(
            evaluation_id=evaluation_id,
            session_id=session_id,
            query=query,
            answer=answer,
            contexts=contexts,
        )
    except Exception as e:
        logger.warning(f"Background evaluation failed (non-blocking): evaluation_id={evaluation_id}, error={e}")
