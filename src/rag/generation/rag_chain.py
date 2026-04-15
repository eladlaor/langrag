"""
RAG Answer Generation Chain

LLM answer generation with citations using the configured provider.
Supports streaming tokens via an async callback.
"""

import logging
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from config import get_settings
from constants import MessageRole
from custom_types.field_keys import RAGConversationKeys as ConvKeys
from rag.generation.prompts import (
    RAG_SYSTEM_PROMPT,
    RAG_USER_PROMPT_TEMPLATE,
    RAG_TITLE_GENERATION_PROMPT,
)
from utils.llm.chat_model_factory import create_chat_model

logger = logging.getLogger(__name__)


async def generate_answer(
    query: str,
    context: str,
    conversation_history: list[dict[str, Any]],
) -> str:
    """
    Generate an answer using the RAG context and conversation history.

    Args:
        query: The user's question
        context: Formatted context string with citation markers
        conversation_history: List of previous messages (role, content)

    Returns:
        Generated answer text with citation markers
    """
    settings = get_settings().rag
    llm = create_chat_model(
        model=settings.rag_llm_model,
        temperature=0.3,
        provider=settings.rag_llm_provider,
    )

    messages = _build_messages(query, context, conversation_history)

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
) -> AsyncIterator[str]:
    """
    Stream answer tokens using the RAG context and conversation history.

    Args:
        query: The user's question
        context: Formatted context string with citation markers
        conversation_history: List of previous messages (role, content)

    Yields:
        Individual token strings as they are generated
    """
    settings = get_settings().rag
    llm = create_chat_model(
        model=settings.rag_llm_model,
        temperature=0.3,
        provider=settings.rag_llm_provider,
    )

    messages = _build_messages(query, context, conversation_history)

    try:
        async for chunk in llm.astream(messages):
            if chunk.content:
                yield chunk.content
    except Exception as e:
        logger.error(f"RAG streaming generation failed: {e}")
        raise RuntimeError(f"Streaming generation failed: {e}") from e


async def generate_session_title(query: str) -> str:
    """
    Generate a short title for a conversation session based on the first query.

    Args:
        query: The first user query in the session

    Returns:
        Short descriptive title (5-8 words)
    """
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
) -> list:
    """Build the LangChain message list for the LLM call."""
    messages = [SystemMessage(content=RAG_SYSTEM_PROMPT)]

    # Format conversation history for the prompt
    history_text = _format_history(conversation_history)

    user_prompt = RAG_USER_PROMPT_TEMPLATE.format(
        context=context,
        history=history_text,
        query=query,
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
