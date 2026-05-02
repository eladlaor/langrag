"""
State Schema for RAG Conversation Graph

Defines the TypedDict state schema for the RAG conversation flow:
retrieve -> generate -> evaluate.
"""

from datetime import datetime
from typing import Any
from typing_extensions import TypedDict


class RAGConversationState(TypedDict, total=False):
    """
    State for the RAG conversation graph.

    Linear flow: retrieve -> generate -> evaluate
    """

    # Input
    session_id: str
    query: str
    content_sources: list[str]
    conversation_history: list[dict[str, Any]]
    date_start: datetime | None
    date_end: datetime | None

    # Retrieval
    retrieved_chunks: list[dict[str, Any]]
    reranked_chunks: list[dict[str, Any]]
    context: str
    freshness_warning: bool
    oldest_source_date: datetime | None
    newest_source_date: datetime | None

    # Generation
    answer: str
    citations: list[dict[str, Any]]

    # Evaluation
    evaluation_id: str | None

    # SSE streaming
    progress_queue: Any | None
