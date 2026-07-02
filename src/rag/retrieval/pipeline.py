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
from constants import COLLECTION_MESSAGES, COLLECTION_RAG_CHUNKS, RAG_CITATION_SNIPPET_MAX_LENGTH, RAG_HYBRID_VECTOR_COSINE_FIELD, RAG_SEARCH_SCORE_FIELD
from custom_types.field_keys import DbFieldKeys, RAGChunkKeys as Keys, RAGChunkMetadataKeys
from db.connection import get_database
from observability.llm.langfuse_client import langfuse_span
from observability.metrics.rag_metrics import (
    record_freshness_warning,
    record_results,
    track_retrieval,
)
from rag.cache.query_embedding_cache import QueryEmbeddingCache
from rag.retrieval.hybrid_search import hybrid_search_chunks
from rag.retrieval.reranker import rerank_chunks_mmr
from rag.retrieval.vector_search import vector_search_chunks
from utils.embedding.factory import EmbeddingProviderFactory

logger = logging.getLogger(__name__)

# Process-wide query-embedding cache (COST-4a). Built lazily from settings so it
# binds after config load and tests can swap it. A repeated normalized query
# within the TTL reuses the cached vector instead of paying for a fresh embedding.
_query_cache_singleton: QueryEmbeddingCache | None = None


def _get_query_cache() -> QueryEmbeddingCache:
    global _query_cache_singleton
    if _query_cache_singleton is None:
        rag = get_settings().rag
        _query_cache_singleton = QueryEmbeddingCache(
            max_size=rag.query_embedding_cache_max_size,
            ttl_seconds=rag.query_embedding_cache_ttl_seconds,
        )
    return _query_cache_singleton


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
        settings = get_settings()
        rag_model = settings.rag_embedding.model or settings.embedding.default_model
        rag_dims = settings.rag_embedding.dimensions if settings.rag_embedding.dimensions is not None else settings.embedding.output_dimensions
        self._embedder = EmbeddingProviderFactory.create(model=rag_model, dimensions=rag_dims)
        self._settings = settings.rag

    async def retrieve(
        self,
        query: str,
        content_sources: list[str] | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
        data_source_names: list[str] | None = None,
        podcast_slug: str | None = None,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
        mmr_lambda: float | None = None,
        enable_mmr: bool | None = None,
        include_raw_messages: bool | None = None,
        unbounded_default_window: bool = False,
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
            mmr_lambda: MMR relevance/diversity weight in [0, 1]. None falls back to
                the config default (rag.mmr_lambda). Higher favors relevance.
            enable_mmr: Whether to apply MMR diversity reranking. None falls back to
                the config default (rag.enable_mmr_diversity). When MMR is skipped
                (disabled, or effective lambda >= 1.0), the fused top-k is returned
                by relevance order, which is mathematically identical to lambda=1.0.

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

        # Resolve the effective MMR settings: explicit arg (from a saved user
        # preference) wins, else the config default. (The per-user saved setting
        # is resolved by callers and passed in as the explicit arg.)
        effective_lambda = mmr_lambda if mmr_lambda is not None else self._settings.mmr_lambda
        effective_enable_mmr = enable_mmr if enable_mmr is not None else self._settings.enable_mmr_diversity

        # Parent-document retrieval (D10): explicit arg (the agent's per-call
        # decision) wins, else the config default.
        effective_include_raw = (
            include_raw_messages if include_raw_messages is not None
            else self._settings.include_raw_messages_default
        )

        # Soft default date window: when the caller gives NO lower bound, default
        # to the recent window (community discourse ages fast). An explicit
        # date_start always wins, including an older one. 0 days disables it.
        # F5: the podcast surface passes unbounded_default_window=True — podcasts
        # are evergreen and sparse, so an unfiltered podcast search must NOT hide
        # episodes older than the window. The community/newsletter surface keeps
        # recent-by-default.
        window_days = self._settings.default_retrieval_window_days
        if date_start is None and window_days > 0 and not unbounded_default_window:
            date_start = datetime.now(UTC) - timedelta(days=window_days)
            logger.info(f"No date_start given; applying soft default window of {window_days}d (from {date_start.date()})")
        elif date_start is None and unbounded_default_window:
            logger.info("No date_start given; unbounded window requested (podcast surface), skipping soft default window")

        # Fail-fast on an out-of-range lambda rather than silently clamping; a
        # bad value almost always means a caller bug we want surfaced.
        if not 0.0 <= effective_lambda <= 1.0:
            raise ValueError(
                f"retrieve: effective mmr_lambda must be in [0.0, 1.0], got {effective_lambda}"
            )

        # Skip the MMR rerank entirely when diversity is disabled or lambda is
        # pure-relevance (>= 1.0): both are mathematically identical to taking
        # the fused top-k by relevance, and skipping is cheaper.
        skip_mmr = (not effective_enable_mmr) or effective_lambda >= 1.0


        source_label = ",".join(sorted(content_sources)) if content_sources else "any"
        date_filter_used = date_start is not None or date_end is not None
        retrieval_mode = "hybrid" if self._settings.hybrid_enabled else "vector"

        span_input = {
            "query": query[:500],
            "content_sources": content_sources,
            "date_start": date_start.isoformat() if date_start else None,
            "date_end": date_end.isoformat() if date_end else None,
            "top_k": top_k,
            "rerank_top_k": rerank_top_k,
            "mmr_lambda": effective_lambda,
            "mmr_applied": not skip_mmr,
            "retrieval_mode": retrieval_mode,
            "effective_lambda": effective_lambda,
            "enable_mmr": effective_enable_mmr,
        }

        with langfuse_span("rag_retrieve", trace_id=trace_id, input_data=span_input) as span, \
             track_retrieval(source_label, date_filter_used):
            # COST-4a: reuse a cached embedding for a repeated (normalized) query
            # within the TTL; only pay for a fresh embedding on a miss.
            cache = _get_query_cache()
            query_embedding = cache.get(query)
            if query_embedding is None:
                query_embedding = await asyncio.to_thread(self._embedder.embed_text, query)
                if query_embedding is None:
                    logger.error(f"Failed to embed query: {query[:100]}")
                    raise RuntimeError("Query embedding failed")
                cache.put(query, query_embedding)

            db = await get_database()
            collection = db[COLLECTION_RAG_CHUNKS]

            if self._settings.hybrid_enabled:
                retrieved = await hybrid_search_chunks(
                    collection=collection,
                    query_text=query,
                    query_embedding=query_embedding,
                    content_sources=content_sources,
                    date_start=date_start,
                    date_end=date_end,
                    data_source_names=data_source_names,
                    podcast_slug=podcast_slug,
                    top_k=search_top_k,
                    min_vector_score=self._settings.min_similarity_score,
                )
            else:
                retrieved = await vector_search_chunks(
                    collection=collection,
                    query_embedding=query_embedding,
                    content_sources=content_sources,
                    date_start=date_start,
                    date_end=date_end,
                    data_source_names=data_source_names,
                    podcast_slug=podcast_slug,
                    top_k=search_top_k,
                    min_score=self._settings.min_similarity_score,
                )

        if not retrieved:
            logger.info(f"No chunks retrieved (mode={retrieval_mode})")
            record_results(source_label, date_filter_used, 0)
            return {
                "retrieved_chunks": [],
                "reranked_chunks": [],
                "context": "",
                "citations": [],
                "freshness_warning": False,
                "oldest_source_date": None,
                "newest_source_date": None,
                "mmr_lambda": effective_lambda,
                "mmr_applied": False,
                "effective_lambda": effective_lambda,
                "enable_mmr": effective_enable_mmr,
            }

        if skip_mmr:
            # Fused results already arrive in relevance order; take the top-k.
            reranked = retrieved[:final_top_k]
        else:
            reranked = rerank_chunks_mmr(
                chunks=retrieved,
                query_embedding=query_embedding,
                top_k=final_top_k,
                lambda_param=effective_lambda,
            )

        # Parent-document expansion (D10): drill from the selected chunks down to
        # the raw underlying messages via a server-side $lookup, attaching them as
        # `parent_messages`. Only the final top-k chunks are expanded (cheap), and
        # only when the caller/agent asked for it.
        if effective_include_raw:
            await self._expand_with_parents(reranked)

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
                "retrieval_mode": retrieval_mode,
                "mmr_lambda": effective_lambda,
                "mmr_applied": not skip_mmr,
            })

        logger.info(
            f"Retrieval complete: mode={retrieval_mode}, "
            f"{len(retrieved)} searched -> {len(reranked)} reranked, "
            f"freshness_warning={freshness_warning}"
        )

        # Strip embedding vectors (large) and the internal hybrid relevance-floor
        # cosine field (an implementation detail) from results before returning.
        for chunk in retrieved:
            chunk.pop(Keys.EMBEDDING, None)
            chunk.pop(RAG_HYBRID_VECTOR_COSINE_FIELD, None)
        for chunk in reranked:
            chunk.pop(Keys.EMBEDDING, None)
            chunk.pop(RAG_HYBRID_VECTOR_COSINE_FIELD, None)

        return {
            "retrieved_chunks": retrieved,
            "reranked_chunks": reranked,
            "context": context,
            "citations": citations,
            "freshness_warning": freshness_warning,
            "oldest_source_date": oldest,
            "newest_source_date": newest,
            "mmr_lambda": effective_lambda,
            "mmr_applied": not skip_mmr,
            "effective_lambda": effective_lambda,
            "enable_mmr": effective_enable_mmr,
            "include_raw_messages": effective_include_raw,
        }

    async def _expand_with_parents(self, chunks: list[dict[str, Any]]) -> None:
        """Attach raw underlying messages to each chunk via a $lookup (D10).

        Parent-document retrieval: each newsletter chunk carries, in its metadata,
        the flattened ids of the raw messages behind it (persisted at ingest).
        This runs a single server-side $lookup from rag_chunks -> messages keyed
        by `metadata.message_ids`, and attaches the resolved messages to each
        chunk under `parent_messages` (sender / content / timestamp, time-ordered,
        capped per chunk). Mutates `chunks` in place.

        This is the only cross-collection $lookup in the codebase; every other
        join is single-collection by design. Chunks with no message provenance
        (legacy / podcast) simply get an empty `parent_messages` list.
        """
        chunk_ids = [c.get(Keys.CHUNK_ID) for c in chunks if c.get(Keys.CHUNK_ID)]
        if not chunk_ids:
            return

        cap = self._settings.parent_messages_per_chunk_cap
        metadata_message_ids_path = f"{Keys.METADATA}.{RAGChunkMetadataKeys.MESSAGE_IDS}"

        try:
            db = await get_database()
            collection = db[COLLECTION_RAG_CHUNKS]

            pipeline = [
                {"$match": {Keys.CHUNK_ID: {"$in": chunk_ids}}},
                {
                    "$lookup": {
                        "from": COLLECTION_MESSAGES,
                        "localField": metadata_message_ids_path,
                        "foreignField": DbFieldKeys.MESSAGE_ID,
                        "as": RAGChunkMetadataKeys.PARENT_MESSAGES,
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        Keys.CHUNK_ID: 1,
                        RAGChunkMetadataKeys.PARENT_MESSAGES: {
                            "$map": {
                                "input": f"${RAGChunkMetadataKeys.PARENT_MESSAGES}",
                                "as": "m",
                                "in": {
                                    DbFieldKeys.MESSAGE_ID: f"$$m.{DbFieldKeys.MESSAGE_ID}",
                                    DbFieldKeys.SENDER: f"$$m.{DbFieldKeys.SENDER}",
                                    DbFieldKeys.CONTENT: f"$$m.{DbFieldKeys.CONTENT}",
                                    DbFieldKeys.TIMESTAMP: f"$$m.{DbFieldKeys.TIMESTAMP}",
                                },
                            }
                        },
                    }
                },
            ]

            rows = await (await collection.aggregate(pipeline)).to_list(len(chunk_ids))
            by_chunk = {row[Keys.CHUNK_ID]: row.get(RAGChunkMetadataKeys.PARENT_MESSAGES, []) for row in rows}

            for chunk in chunks:
                messages = by_chunk.get(chunk.get(Keys.CHUNK_ID), [])
                # Time-order so the LLM reads the discussion as it unfolded.
                messages.sort(key=lambda m: m.get(DbFieldKeys.TIMESTAMP) or 0)
                if len(messages) > cap:
                    logger.warning(
                        "Parent expansion: chunk %s has %d messages, capping to %d",
                        chunk.get(Keys.CHUNK_ID), len(messages), cap,
                    )
                    messages = messages[:cap]
                chunk[RAGChunkMetadataKeys.PARENT_MESSAGES] = messages

        except Exception as e:
            logger.error(f"Parent-document expansion failed: {e}")
            raise

    @staticmethod
    def _format_context(chunks: list[dict[str, Any]]) -> tuple[str, list[dict]]:
        """
        Format reranked chunks into a context string with citation markers and source dates.

        The LLM sees, per chunk, the marker, source title, and source date range,
        so it can cite freshness alongside facts.
        """
        context_parts = []
        citations = []
        # Collected separately so raw messages form one dedicated section at the
        # end of the context, keyed back to each chunk marker — the chunk summary
        # blocks above stay untouched.
        primary_source_blocks = []

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

            parent_messages = chunk.get(RAGChunkMetadataKeys.PARENT_MESSAGES) or []
            if parent_messages:
                lines = "\n".join(
                    f"  {m.get(DbFieldKeys.SENDER, '?')}: {m.get(DbFieldKeys.CONTENT, '')}"
                    for m in parent_messages
                )
                primary_source_blocks.append(f"{marker} raw messages:\n{lines}")

            citation = {
                "index": i,
                "chunk_id": chunk.get(Keys.CHUNK_ID, ""),
                "source_id": chunk.get(Keys.SOURCE_ID, ""),
                "source_type": chunk.get(Keys.CONTENT_SOURCE, ""),
                "source_title": source_title,
                "source_date_start": _to_iso(date_start),
                "source_date_end": _to_iso(date_end),
                "snippet": content[:RAG_CITATION_SNIPPET_MAX_LENGTH],
                "search_score": chunk.get(RAG_SEARCH_SCORE_FIELD, 0.0),
                "metadata": metadata,
                RAGChunkMetadataKeys.PARENT_MESSAGES: parent_messages,
            }
            citations.append(citation)

        context = "\n\n".join(context_parts)
        if primary_source_blocks:
            primary_section = "\n\n".join(primary_source_blocks)
            context = (
                f"{context}\n\n"
                f"--- PRIMARY SOURCES (raw messages behind the cited newsletters) ---\n"
                f"{primary_section}"
            )
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
