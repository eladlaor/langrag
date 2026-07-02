"""
MCP tool implementations.

The tools are thin orchestrators that reuse the existing RAG primitives:
RetrievalPipeline, generate_answer, and the chunk repository. They never
invent new behaviour — every code path is exercised by the REST API too,
so eval results apply identically.
"""

from datetime import UTC, datetime
from typing import Any

from constants import (
    ContentSourceType,
    RAG_TRACE_META_CITATION_COUNT,
    RAG_TRACE_META_REFUSAL,
    RAG_TRACE_OUTPUT_ANSWER,
    RAGTraceName,
    RAGTraceTag,
)
from custom_types.field_keys import RAGChunkKeys
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from observability.llm.langfuse_client import flush_langfuse, get_langfuse_callback_handler
from observability.llm.rag_tracing import create_rag_trace, schedule_rag_online_eval
from rag.concurrency.guard import rag_slot
from rag.generation.rag_chain import generate_answer, refusal_for_empty_context
from rag.retrieval.pipeline import RetrievalPipeline


def _parse_iso_date(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"Invalid {label}: '{value}'. Expected YYYY-MM-DD or ISO 8601.") from e
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_or_none(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


async def rag_query(
    query: str,
    date_start: str | None = None,
    date_end: str | None = None,
    sources: list[str] | None = None,
    communities: list[str] | None = None,
    mmr_lambda: float | None = None,
    include_raw_messages: bool | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run the full RAG chain (retrieve + generate) and return a dated answer.

    Returns a dict with the answer text, citations (each carrying source dates),
    and the freshness summary so calling agents can render staleness warnings.

    `communities` optionally restricts retrieval to specific communities
    (data_source_name, e.g. ["langtalks"]); podcasts are excluded when set.

    `mmr_lambda` (0-1) optionally overrides the server default MMR relevance/
    diversity balance for this query; None falls back to the config default.

    `include_raw_messages` (parent-document retrieval): when true, the retrieval
    drills from each cited newsletter chunk down to the raw underlying messages
    and injects them into the generator's context as a primary-sources section,
    so the answer can draw on the original messages, not just the summary. None
    falls back to the config default.
    """
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")

    trace, trace_id = create_rag_trace(
        name=RAGTraceName.MCP_QUERY,
        user_id=user_id,
        session_id=session_id,
        query=query,
        content_sources=sources,
        date_start=ds,
        date_end=de,
        tags=[RAGTraceTag.RAG, RAGTraceTag.MCP],
    )

    # Concurrency admission control against the SAME process-wide budget as the
    # REST surface. RagCapacityExceeded propagates to the MCP caller (the MCP
    # framework surfaces it as a tool error); the slot is released in finally,
    # so a pipeline/generation error never leaks it.
    try:
        async with rag_slot():
            # MCP tool signatures carry no caller identity, so per-user MMR lambda is
            # not resolvable here; retrieval falls through to the config default.
            pipeline = RetrievalPipeline()
            retrieval = await pipeline.retrieve(
                query=query,
                content_sources=sources,
                date_start=ds,
                date_end=de,
                data_source_names=communities,
                mmr_lambda=mmr_lambda,
                include_raw_messages=include_raw_messages,
                trace_id=trace_id,
            )

            if not retrieval["context"]:
                answer = refusal_for_empty_context(ds, de)
                if trace:
                    trace.update(output={RAG_TRACE_OUTPUT_ANSWER: answer}, metadata={RAG_TRACE_META_REFUSAL: True})
            else:
                callback = get_langfuse_callback_handler(trace_id=trace_id, session_id=session_id, user_id=user_id)
                answer = await generate_answer(
                    query=query,
                    context=retrieval["context"],
                    conversation_history=[],
                    date_start=ds,
                    date_end=de,
                    freshness_warning=retrieval["freshness_warning"],
                    newest_source_date=retrieval["newest_source_date"],
                    callbacks=[callback] if callback else None,
                )
                if trace:
                    trace.update(
                        output={RAG_TRACE_OUTPUT_ANSWER: answer},
                        metadata={RAG_TRACE_META_REFUSAL: False, RAG_TRACE_META_CITATION_COUNT: len(retrieval["citations"])},
                    )
                schedule_rag_online_eval(
                    session_id=session_id or trace_id or "",
                    query=query,
                    answer=answer,
                    contexts=[retrieval["context"]],
                    trace_id=trace_id,
                )

            return {
                "answer": answer,
                "citations": retrieval["citations"],
                "freshness_warning": retrieval["freshness_warning"],
                "oldest_source_date": _iso_or_none(retrieval["oldest_source_date"]),
                "newest_source_date": _iso_or_none(retrieval["newest_source_date"]),
                "date_filter": {
                    "date_start": _iso_or_none(ds),
                    "date_end": _iso_or_none(de),
                },
                "sources": sources or [],
            }
    finally:
        flush_langfuse()


async def rag_search(
    query: str,
    date_start: str | None = None,
    date_end: str | None = None,
    sources: list[str] | None = None,
    communities: list[str] | None = None,
    top_k: int | None = None,
    mmr_lambda: float | None = None,
    include_raw_messages: bool | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run retrieval only — no LLM call. Returns reranked citations with source dates.

    `communities` optionally restricts retrieval to specific communities
    (data_source_name, e.g. ["langtalks"]); podcasts are excluded when set.

    `mmr_lambda` (0-1) optionally overrides the server default MMR relevance/
    diversity balance for this query; None falls back to the config default.

    `include_raw_messages` (parent-document retrieval): when true, each returned
    citation also carries the raw underlying messages behind that chunk
    (`parent_messages`). None falls back to the config default.
    """
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")

    trace, trace_id = create_rag_trace(
        name=RAGTraceName.MCP_SEARCH,
        user_id=user_id,
        session_id=session_id,
        query=query,
        content_sources=sources,
        date_start=ds,
        date_end=de,
        tags=[RAGTraceTag.RAG, RAGTraceTag.MCP],
    )

    # Concurrency admission control against the same process-wide budget as the
    # REST surface (retrieval-only, but still an expensive execution path).
    try:
        async with rag_slot():
            # No caller identity on the MCP path: per-user MMR lambda is not resolvable,
            # so retrieval uses the config default.
            pipeline = RetrievalPipeline()
            retrieval = await pipeline.retrieve(
                query=query,
                content_sources=sources,
                date_start=ds,
                date_end=de,
                data_source_names=communities,
                rerank_top_k=top_k,
                mmr_lambda=mmr_lambda,
                include_raw_messages=include_raw_messages,
                trace_id=trace_id,
            )

            # Retrieval-only path: no generation, no online eval. An empty
            # citation set is the refusal signal (nothing matched the query).
            if trace:
                citations = retrieval["citations"]
                trace.update(
                    metadata={RAG_TRACE_META_REFUSAL: not citations, RAG_TRACE_META_CITATION_COUNT: len(citations)},
                )

            return {
                "citations": retrieval["citations"],
                "freshness_warning": retrieval["freshness_warning"],
                "oldest_source_date": _iso_or_none(retrieval["oldest_source_date"]),
                "newest_source_date": _iso_or_none(retrieval["newest_source_date"]),
                "date_filter": {
                    "date_start": _iso_or_none(ds),
                    "date_end": _iso_or_none(de),
                },
                "sources": sources or [],
            }
    finally:
        flush_langfuse()


async def list_rag_sources() -> dict[str, list[dict[str, Any]]]:
    """List ingested sources grouped by type, with chunk counts and earliest/latest dates."""
    db = await get_database()
    repo = ChunksRepository(db)

    result: dict[str, list[dict[str, Any]]] = {
        str(ContentSourceType.PODCAST): [],
        str(ContentSourceType.NEWSLETTER): [],
    }

    pipeline = [
        {
            "$group": {
                "_id": {
                    RAGChunkKeys.CONTENT_SOURCE: f"${RAGChunkKeys.CONTENT_SOURCE}",
                    RAGChunkKeys.SOURCE_ID: f"${RAGChunkKeys.SOURCE_ID}",
                },
                "source_title": {"$first": f"${RAGChunkKeys.SOURCE_TITLE}"},
                "chunk_count": {"$sum": 1},
                "source_date_start": {"$min": f"${RAGChunkKeys.SOURCE_DATE_START}"},
                "source_date_end": {"$max": f"${RAGChunkKeys.SOURCE_DATE_END}"},
                "ingested_at": {"$min": f"${RAGChunkKeys.CREATED_AT}"},
            }
        },
        {"$sort": {"source_date_end": -1}},
    ]

    cursor = await repo.collection.aggregate(pipeline)
    async for doc in cursor:
        bucket = doc["_id"][RAGChunkKeys.CONTENT_SOURCE]
        entry = {
            "source_id": doc["_id"][RAGChunkKeys.SOURCE_ID],
            "source_title": doc.get("source_title"),
            "chunk_count": doc.get("chunk_count", 0),
            "source_date_start": _iso_or_none(doc.get("source_date_start")),
            "source_date_end": _iso_or_none(doc.get("source_date_end")),
            "ingested_at": _iso_or_none(doc.get("ingested_at")),
        }
        result.setdefault(bucket, []).append(entry)

    return result
