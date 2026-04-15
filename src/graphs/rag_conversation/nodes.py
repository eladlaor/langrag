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

# Track background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task] = set()


async def retrieve_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Retrieve relevant chunks for the user query.

    - Embeds the query
    - Runs vector search filtered by content_sources
    - Reranks with MMR for diversity
    - Formats context string with citations
    """
    query = state[Keys.QUERY]
    content_sources = state.get(Keys.CONTENT_SOURCES) or None

    logger.info(f"RAG retrieve: query='{query[:80]}...', sources={content_sources}")

    pipeline = RetrievalPipeline()
    result = await pipeline.retrieve(
        query=query,
        content_sources=content_sources,
    )

    return {
        Keys.RETRIEVED_CHUNKS: result["retrieved_chunks"],
        Keys.RERANKED_CHUNKS: result["reranked_chunks"],
        Keys.CONTEXT: result["context"],
        Keys.CITATIONS: result["citations"],
    }


async def generate_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Generate an answer using the retrieved context and conversation history.

    Uses the configured LLM provider to produce a response with citation markers.
    """
    query = state[Keys.QUERY]
    context = state.get(Keys.CONTEXT, "")
    history = state.get(Keys.CONVERSATION_HISTORY, [])

    if not context:
        answer = "I couldn't find any relevant information in the available sources to answer your question. Could you try rephrasing or asking about a different topic?"
        return {Keys.ANSWER: answer}

    logger.info(f"RAG generate: query='{query[:80]}...', context_len={len(context)}")

    answer = await generate_answer(
        query=query,
        context=context,
        conversation_history=history,
    )

    return {Keys.ANSWER: answer}


async def evaluate_node(state: RAGConversationState) -> dict[str, Any]:
    """
    Conditionally fire background DeepEval evaluation.

    Non-blocking: creates an asyncio task for evaluation.
    If DeepEval is disabled, returns immediately with no evaluation_id.
    """
    settings = get_settings().deepeval

    if not settings.enabled:
        return {Keys.EVALUATION_ID: None}

    # Sampling: skip evaluation based on sampling_rate
    if random.random() > settings.sampling_rate:
        return {Keys.EVALUATION_ID: None}

    evaluation_id = str(uuid.uuid4())

    # Fire background evaluation task (stored in set to prevent GC)
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
    """
    Run DeepEval evaluation in the background.

    Fail-soft: catches all exceptions and logs them without crashing the conversation.
    """
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
