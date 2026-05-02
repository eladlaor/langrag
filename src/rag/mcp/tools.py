"""
MCP tool implementations.

The tools are thin orchestrators that reuse the existing RAG primitives:
RetrievalPipeline, generate_answer, and the chunk repository. They never
invent new behaviour — every code path is exercised by the REST API too,
so eval results apply identically.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from constants import ContentSourceType
from custom_types.field_keys import RAGChunkKeys
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from rag.generation.rag_chain import generate_answer
from rag.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)


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
) -> dict[str, Any]:
    """Run the full RAG chain (retrieve + generate) and return a dated answer.

    Returns a dict with the answer text, citations (each carrying source dates),
    and the freshness summary so calling agents can render staleness warnings.
    """
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")

    pipeline = RetrievalPipeline()
    retrieval = await pipeline.retrieve(
        query=query,
        content_sources=sources,
        date_start=ds,
        date_end=de,
    )

    if not retrieval["context"]:
        if ds or de:
            answer = (
                "No content was found within the requested date range. "
                "Broaden the window or rephrase the question."
            )
        else:
            answer = "No relevant content found in the indexed sources."
    else:
        answer = await generate_answer(
            query=query,
            context=retrieval["context"],
            conversation_history=[],
            date_start=ds,
            date_end=de,
            freshness_warning=retrieval["freshness_warning"],
            newest_source_date=retrieval["newest_source_date"],
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


async def rag_search(
    query: str,
    date_start: str | None = None,
    date_end: str | None = None,
    sources: list[str] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Run retrieval only — no LLM call. Returns reranked citations with source dates."""
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")

    pipeline = RetrievalPipeline()
    retrieval = await pipeline.retrieve(
        query=query,
        content_sources=sources,
        date_start=ds,
        date_end=de,
        rerank_top_k=top_k,
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

    cursor = repo.collection.aggregate(pipeline)
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
