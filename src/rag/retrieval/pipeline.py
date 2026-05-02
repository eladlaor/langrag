"""
RAG Retrieval Pipeline

Source-agnostic retrieval flow: embed query -> vector search -> rerank -> format context.
Every retrieved chunk surfaces its source date range in both the context block
(so the LLM can cite freshness) and the citations payload (so callers can scope
or display the source date).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from config import get_settings
from constants import COLLECTION_RAG_CHUNKS, RAG_CITATION_SNIPPET_MAX_LENGTH, RAG_SEARCH_SCORE_FIELD
from custom_types.field_keys import RAGChunkKeys as Keys
from db.connection import get_database
from observability.llm.langfuse_client import langfuse_span
from observability.metrics.rag_metrics import (
    record_freshness_warning,
    record_results,
    track_retrieval,
)
from rag.retrieval.reranker import rerank_chunks_mmr
from rag.retrieval.vector_search import vector_search_chunks
from utils.embedding.factory import EmbeddingProviderFactory

logger = logging.getLogger(__name__)


class RetrievalPipeline:
    """
    Source-agnostic retrieval pipeline for RAG.

    Flow:
    1. Embed the user query
    2. Vector search on rag_chunks (filtered by content_source and/or date range)
    3. Rerank with MMR for diversity
    4. Format context string with citations + source dates for LLM prompt
    """

    def __init__(self) -> None:
        self._embedder = EmbeddingProviderFactory.create()
        self._settings = get_settings().rag

    async def retrieve(
        self,
        query: str,
        content_sources: list[str] | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Full retrieval pipeline: embed -> search -> rerank -> format.

        Args:
            query: User query text
            content_sources: Optional content source type filter (e.g., ["podcast"])
            date_start: Optional inclusive lower bound on source date range
            date_end: Optional inclusive upper bound on source date range
            top_k: Override for vector search top-K (default from config)
            rerank_top_k: Override for rerank top-K (default from config)

        Returns:
            Dict with:
                - retrieved_chunks: Raw chunks from vector search
                - reranked_chunks: Chunks after MMR reranking
                - context: Formatted context string for LLM prompt (with source dates)
                - citations: Citation metadata list (with source_date_start/end)
                - freshness_warning: True if any retrieved chunk is older than the
                  configured freshness threshold
                - oldest_source_date: Earliest source date across reranked chunks
                - newest_source_date: Latest source date across reranked chunks
        """
        search_top_k = top_k or self._settings.vector_search_top_k
        final_top_k = rerank_top_k or self._settings.rerank_top_k

        source_label = ",".join(sorted(content_sources)) if content_sources else "any"
        date_filter_used = date_start is not None or date_end is not None

        span_input = {
            "query": query[:500],
            "content_sources": content_sources,
            "date_start": date_start.isoformat() if date_start else None,
            "date_end": date_end.isoformat() if date_end else None,
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
        }

        with langfuse_span("rag_retrieve", trace_id=trace_id, input_data=span_input) as span, \
             track_retrieval(source_label, date_filter_used):
            query_embedding = await asyncio.to_thread(self._embedder.embed_text, query)
            if query_embedding is None:
                logger.error(f"Failed to embed query: {query[:100]}")
                raise RuntimeError("Query embedding failed")

            db = await get_database()
            collection = db[COLLECTION_RAG_CHUNKS]

            retrieved = await vector_search_chunks(
                collection=collection,
                query_embedding=query_embedding,
                content_sources=content_sources,
                date_start=date_start,
                date_end=date_end,
                top_k=search_top_k,
                min_score=self._settings.min_similarity_score,
            )

        if not retrieved:
            logger.info("No chunks retrieved from vector search")
            record_results(source_label, date_filter_used, 0)
            return {
                "retrieved_chunks": [],
                "reranked_chunks": [],
                "context": "",
                "citations": [],
                "freshness_warning": False,
                "oldest_source_date": None,
                "newest_source_date": None,
            }

        reranked = rerank_chunks_mmr(
            chunks=retrieved,
            query_embedding=query_embedding,
            top_k=final_top_k,
        )

        context, citations = self._format_context(reranked)
        freshness_warning, oldest, newest = self._evaluate_freshness(reranked)

        record_results(source_label, date_filter_used, len(reranked))
        if freshness_warning:
            record_freshness_warning(source_label)

        if span:
            span.update(output={
                "reranked_count": len(reranked),
                "retrieved_count": len(retrieved),
                "freshness_warning": freshness_warning,
                "oldest_source_date": oldest.isoformat() if oldest else None,
                "newest_source_date": newest.isoformat() if newest else None,
            })

        logger.info(
            f"Retrieval complete: {len(retrieved)} searched -> {len(reranked)} reranked, "
            f"freshness_warning={freshness_warning}"
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
            "freshness_warning": freshness_warning,
            "oldest_source_date": oldest,
            "newest_source_date": newest,
        }

    @staticmethod
    def _format_context(chunks: list[dict[str, Any]]) -> tuple[str, list[dict]]:
        """
        Format reranked chunks into a context string with citation markers and source dates.

        The LLM sees, per chunk, the marker, source title, and source date range,
        so it can cite freshness alongside facts.
        """
        context_parts = []
        citations = []

        for i, chunk in enumerate(chunks, start=1):
            marker = f"[{i}]"
            content = chunk.get(Keys.CONTENT, "")
            source_title = chunk.get(Keys.SOURCE_TITLE, "Unknown")
            metadata = chunk.get(Keys.METADATA, {})
            date_start = chunk.get(Keys.SOURCE_DATE_START)
            date_end = chunk.get(Keys.SOURCE_DATE_END)

            date_tag = _format_date_tag(date_start, date_end)
            context_parts.append(
                f"{marker} (source: {source_title}; {date_tag})\n{content}"
            )

            citation = {
                "index": i,
                "chunk_id": chunk.get(Keys.CHUNK_ID, ""),
                "source_type": chunk.get(Keys.CONTENT_SOURCE, ""),
                "source_title": source_title,
                "source_date_start": _to_iso(date_start),
                "source_date_end": _to_iso(date_end),
                "snippet": content[:RAG_CITATION_SNIPPET_MAX_LENGTH],
                "search_score": chunk.get(RAG_SEARCH_SCORE_FIELD, 0.0),
                "metadata": metadata,
            }
            citations.append(citation)

        context = "\n\n".join(context_parts)
        return context, citations

    def _evaluate_freshness(
        self, chunks: list[dict[str, Any]]
    ) -> tuple[bool, datetime | None, datetime | None]:
        """
        Determine whether retrieved chunks should trigger a staleness warning.

        Returns (freshness_warning, oldest, newest) where freshness_warning is True
        if the newest source date among retrieved chunks is older than the configured
        freshness threshold (the AI field moves fast and answers should flag this).
        """
        threshold_days = self._settings.freshness_warning_days
        if threshold_days <= 0 or not chunks:
            return False, None, None

        dates = [chunk.get(Keys.SOURCE_DATE_END) for chunk in chunks if chunk.get(Keys.SOURCE_DATE_END)]
        if not dates:
            return False, None, None

        oldest = min(dates)
        newest = max(dates)
        cutoff = datetime.now(UTC) - timedelta(days=threshold_days)
        # Normalise tz to compare safely
        newest_aware = newest if newest.tzinfo else newest.replace(tzinfo=UTC)
        warn = newest_aware < cutoff
        return warn, oldest, newest


def _format_date_tag(date_start: Any, date_end: Any) -> str:
    """Render a chunk's date range as 'date: YYYY-MM-DD' or 'dates: A to B'."""
    s = _to_iso_date(date_start)
    e = _to_iso_date(date_end)
    if s and e and s == e:
        return f"date: {s}"
    if s and e:
        return f"dates: {s} to {e}"
    if s:
        return f"date: {s}"
    return "date: unknown"


def _to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _to_iso_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None
