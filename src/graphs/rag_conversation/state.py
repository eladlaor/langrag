"""
State Schema for RAG Conversation Graph

Defines the TypedDict state schema for the RAG conversation flow:
retrieve -> generate -> evaluate.
"""

from typing import Any
from typing_extensions import TypedDict


class RAGConversationState(TypedDict):
    """
    State for the RAG conversation graph.

    Linear flow: retrieve -> generate -> evaluate

    Fields:
    - session_id: Conversation session identifier
    - query: Current user query
    - content_sources: Content source types to search (e.g., ["podcast"])
    - conversation_history: Previous messages for context
    - retrieved_chunks: Raw chunks from vector search
    - reranked_chunks: Chunks after MMR reranking
    - context: Formatted context string for LLM prompt
    - answer: Generated answer text
    - citations: Citation metadata list
    - evaluation_id: DeepEval evaluation record ID (if enabled)
    - progress_queue: Optional async queue for SSE streaming
    """

    # Input
    session_id: str
    query: str
    content_sources: list[str]
    conversation_history: list[dict[str, Any]]

    # Retrieval
    retrieved_chunks: list[dict[str, Any]]
    reranked_chunks: list[dict[str, Any]]
    context: str

    # Generation
    answer: str
    citations: list[dict[str, Any]]

    # Evaluation
    evaluation_id: str | None

    # SSE streaming
    progress_queue: Any | None
