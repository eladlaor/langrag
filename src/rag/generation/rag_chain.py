"""
RAG Answer Generation Chain

LLM answer generation with citations using the configured provider.
Supports streaming tokens via an async callback. The prompt enforces date-tagged
citations and surfaces a freshness warning when retrieved content is older than
the configured threshold.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from config import get_settings
from custom_types.field_keys import RAGConversationKeys as ConvKeys
from rag.generation.prompts import (
    RAG_DATE_FILTER_NOTE_TEMPLATE,
    RAG_FRESHNESS_WARNING_TEMPLATE,
    RAG_SYSTEM_PROMPT,
    RAG_TITLE_GENERATION_PROMPT,
    RAG_USER_PROMPT_TEMPLATE,
)
from utils.llm.chat_model_factory import create_chat_model

logger = logging.getLogger(__name__)


async def generate_answer(
    query: str,
    context: str,
    conversation_history: list[dict[str, Any]],
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    freshness_warning: bool = False,
    newest_source_date: datetime | None = None,
) -> str:
    """Generate an answer using the RAG context and conversation history."""
    settings = get_settings().rag
    llm = create_chat_model(
        model=settings.rag_llm_model,
        temperature=0.3,
        provider=settings.rag_llm_provider,
    )

    messages = _build_messages(
        query, context, conversation_history,
        date_start=date_start,
        date_end=date_end,
        freshness_warning=freshness_warning,
        newest_source_date=newest_source_date,
    )

    try:
        response = await llm.ainvoke(messages)
        return response.content
    except Exception as e:
        logger.error(f"RAG generation failed: {e}")
        raise RuntimeError(f"Answer generation failed: {e}") from e


async def generate_answer_stream(
    query: str,
    context: str,
    conversation_history: list[dict[str, Any]],
    *,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    freshness_warning: bool = False,
    newest_source_date: datetime | None = None,
) -> AsyncIterator[str]:
    """Stream answer tokens using the RAG context and conversation history."""
    settings = get_settings().rag
    llm = create_chat_model(
        model=settings.rag_llm_model,
        temperature=0.3,
        provider=settings.rag_llm_provider,
    )

    messages = _build_messages(
        query, context, conversation_history,
        date_start=date_start,
        date_end=date_end,
        freshness_warning=freshness_warning,
        newest_source_date=newest_source_date,
    )

    try:
        async for chunk in llm.astream(messages):
            if chunk.content:
                yield chunk.content
    except Exception as e:
        logger.error(f"RAG streaming generation failed: {e}")
        raise RuntimeError(f"Streaming generation failed: {e}") from e


async def generate_session_title(query: str) -> str:
    """Generate a short title for a conversation session based on the first query."""
    settings = get_settings().rag
    llm = create_chat_model(
        model=settings.rag_llm_model,
        temperature=0.5,
        provider=settings.rag_llm_provider,
    )

    prompt = RAG_TITLE_GENERATION_PROMPT.format(query=query)
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip().strip('"')
    except Exception as e:
        logger.warning(f"Title generation failed, using fallback: {e}")
        return query[:50]


def _build_messages(
    query: str,
    context: str,
    conversation_history: list[dict[str, Any]],
    *,
    date_start: datetime | None,
    date_end: datetime | None,
    freshness_warning: bool,
    newest_source_date: datetime | None,
) -> list:
    """Build the LangChain message list for the LLM call."""
    messages = [SystemMessage(content=RAG_SYSTEM_PROMPT)]

    history_text = _format_history(conversation_history)

    date_filter_block = ""
    if date_start is not None or date_end is not None:
        date_filter_block = RAG_DATE_FILTER_NOTE_TEMPLATE.format(
            date_start=_iso(date_start) or "earliest",
            date_end=_iso(date_end) or "latest",
        )

    freshness_block = ""
    if freshness_warning and newest_source_date is not None:
        freshness_block = RAG_FRESHNESS_WARNING_TEMPLATE.format(
            newest_date=newest_source_date.date().isoformat(),
        )

    user_prompt = RAG_USER_PROMPT_TEMPLATE.format(
        context=context,
        history=history_text,
        query=query,
        date_filter_block=date_filter_block,
        freshness_block=freshness_block,
    )

    messages.append(HumanMessage(content=user_prompt))
    return messages


def _format_history(conversation_history: list[dict[str, Any]]) -> str:
    """Format conversation history into a readable string."""
    if not conversation_history:
        return "(No previous messages)"

    parts = []
    for msg in conversation_history:
        role = msg.get(ConvKeys.ROLE, "unknown")
        content = msg.get(ConvKeys.CONTENT, "")
        parts.append(f"{role}: {content}")

    return "\n".join(parts)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()
