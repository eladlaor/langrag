"""
RAG Retrieval Pipeline

Source-agnostic retrieval flow: embed query -> vector search -> rerank -> format context.
"""

import asyncio
import logging
from typing import Any

from config import get_settings
from constants import COLLECTION_RAG_CHUNKS, RAG_CITATION_SNIPPET_MAX_LENGTH, RAG_SEARCH_SCORE_FIELD
from custom_types.field_keys import RAGChunkKeys as Keys
from db.connection import get_database
from rag.retrieval.reranker import rerank_chunks_mmr
from rag.retrieval.vector_search import vector_search_chunks
from utils.embedding.factory import EmbeddingProviderFactory

logger = logging.getLogger(__name__)


class RetrievalPipeline:
    """
    Source-agnostic retrieval pipeline for RAG.

    Flow:
    1. Embed the user query
    2. Vector search on rag_chunks (filtered by content_source if specified)
    3. Rerank with MMR for diversity
    4. Format context string with citations for LLM prompt
    """

    def __init__(self) -> None:
        self._embedder = EmbeddingProviderFactory.create()
        self._settings = get_settings().rag

    async def retrieve(
        self,
        query: str,
        content_sources: list[str] | None = None,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Full retrieval pipeline: embed -> search -> rerank -> format.

        Args:
            query: User query text
            content_sources: Optional content source type filter (e.g., ["podcast"])
            top_k: Override for vector search top-K (default from config)
            rerank_top_k: Override for rerank top-K (default from config)

        Returns:
            Dict with:
                - retrieved_chunks: Raw chunks from vector search
                - reranked_chunks: Chunks after MMR reranking
                - context: Formatted context string for LLM prompt
                - citations: Citation metadata list
        """
        search_top_k = top_k or self._settings.vector_search_top_k
        final_top_k = rerank_top_k or self._settings.rerank_top_k

        # Step 1: Embed query
        query_embedding = await asyncio.to_thread(self._embedder.embed_text, query)
        if query_embedding is None:
            logger.error(f"Failed to embed query: {query[:100]}")
            raise RuntimeError("Query embedding failed")

        # Step 2: Vector search
        db = await get_database()
        collection = db[COLLECTION_RAG_CHUNKS]

        retrieved = await vector_search_chunks(
            collection=collection,
            query_embedding=query_embedding,
            content_sources=content_sources,
            top_k=search_top_k,
            min_score=self._settings.min_similarity_score,
        )

        if not retrieved:
            logger.info("No chunks retrieved from vector search")
            return {
                "retrieved_chunks": [],
                "reranked_chunks": [],
                "context": "",
                "citations": [],
            }

        # Step 3: Rerank with MMR
        reranked = rerank_chunks_mmr(
            chunks=retrieved,
            query_embedding=query_embedding,
            top_k=final_top_k,
        )

        # Step 4: Format context and citations
        context, citations = self._format_context(reranked)

        logger.info(
            f"Retrieval complete: {len(retrieved)} searched -> {len(reranked)} reranked"
        )

        # Strip embedding vectors from results (large, not needed downstream)
        for chunk in retrieved:
            chunk.pop(Keys.EMBEDDING, None)
        for chunk in reranked:
            chunk.pop(Keys.EMBEDDING, None)

        return {
            "retrieved_chunks": retrieved,
            "reranked_chunks": reranked,
            "context": context,
            "citations": citations,
        }

    @staticmethod
    def _format_context(chunks: list[dict[str, Any]]) -> tuple[str, list[dict]]:
        """
        Format reranked chunks into a context string with citation markers.

        Returns:
            Tuple of (context_string, citations_list)
        """
        context_parts = []
        citations = []

        for i, chunk in enumerate(chunks, start=1):
            marker = f"[{i}]"
            content = chunk.get(Keys.CONTENT, "")
            source_title = chunk.get(Keys.SOURCE_TITLE, "Unknown")
            metadata = chunk.get(Keys.METADATA, {})

            # Build context entry with citation marker
            context_parts.append(f"{marker} {content}")

            # Build citation metadata
            citation = {
                "index": i,
                "chunk_id": chunk.get(Keys.CHUNK_ID, ""),
                "source_type": chunk.get(Keys.CONTENT_SOURCE, ""),
                "source_title": source_title,
                "snippet": content[:RAG_CITATION_SNIPPET_MAX_LENGTH],
                "search_score": chunk.get(RAG_SEARCH_SCORE_FIELD, 0.0),
                "metadata": metadata,
            }
            citations.append(citation)

        context = "\n\n".join(context_parts)
        return context, citations
