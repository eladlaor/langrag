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

from constants import (
    ContentSourceType,
    MCP_TOOL_SEARCH_PODCASTS,
    RAG_REFUSAL_INSUFFICIENT_EVIDENCE,
    RAG_REJECT_REASON_GLOBAL_EMBED_BREAKER,
    RAG_REJECT_REASON_VALIDATION,
    RAG_TRACE_META_CITATION_COUNT,
    RAG_TRACE_META_REFUSAL,
    RAG_TRACE_OUTPUT_ANSWER,
    RAGTraceName,
    RAGTraceTag,
)
from config import get_settings
from custom_types.field_keys import PodcastCatalogKeys, RAGApiKeyKeys, RAGChunkKeys
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from db.repositories.podcasts import PodcastsRepository
from observability.llm.langfuse_client import flush_langfuse, get_langfuse_callback_handler
from observability.llm.rag_tracing import create_rag_trace, schedule_rag_online_eval
from rag.concurrency.guard import rag_slot
from rag.generation.grounding import find_ungrounded_date_tags, is_evidence_sufficient
from rag.generation.rag_chain import generate_answer, refusal_for_empty_context
from rag.mcp.auth_context import get_current_key_record, is_anonymous_key_id
from rag.mcp.validation import MCPToolInputError, clamp_top_k, validate_date_range, validate_podcast_slug, validate_query
from rag.observability.reject_events import emit_reject
from rag.quota.admission import QueryAdmissionError, enforce_anonymous_admission, enforce_query_admission
from rag.quota.daily_quota import DailyQueryQuotaRepository
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


def resolve_current_key_id() -> str | None:
    """Return the resolved per-key id from the auth context, or None on stdio.

    Reads the ContextVar populated by the SSE auth middleware (owned by the auth
    layer). The key_id / hash is safe to surface (OBS-1 tags traces with it); the
    raw bearer is never exposed here. None on stdio (no key record) so internal
    behaviour is unchanged.
    """
    record = get_current_key_record()
    if record is None:
        return None
    return record.get(RAGApiKeyKeys.KEY_ID)


async def _get_quota_repo() -> DailyQueryQuotaRepository:
    """Build the daily-quota repository against the shared DB connection."""
    db = await get_database()
    return DailyQueryQuotaRepository(db)


async def check_global_embed_breaker() -> None:
    """Global daily embedding circuit breaker (COST-4b). Raise if tripped.

    A hard stop bounding TOTAL owner-paid embedding exposure across ALL keys,
    regardless of key count. Runs BEFORE the embedding call; over the daily max it
    raises QueryAdmissionError so no embedding happens.
    """
    rag = get_settings().rag
    repo = await _get_quota_repo()
    within = await repo.check_and_increment_global_embed(limit=rag.mcp_global_embed_daily_max)
    if not within:
        raise QueryAdmissionError(
            "The service is at its global daily capacity. Please try again tomorrow (UTC).",
            reason=RAG_REJECT_REASON_GLOBAL_EMBED_BREAKER,
        )


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
    query = validate_query(query)
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")
    validate_date_range(ds, de)

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

            evidence_floor = get_settings().rag.min_answer_evidence_score
            if not retrieval["context"]:
                answer = refusal_for_empty_context(ds, de)
                if trace:
                    trace.update(output={RAG_TRACE_OUTPUT_ANSWER: answer}, metadata={RAG_TRACE_META_REFUSAL: True})
            elif not is_evidence_sufficient(retrieval["citations"], evidence_floor):
                # Evidence gate: retrieval returned only weakly-related chunks —
                # generating would invite a parametric (hallucinated) answer.
                answer = RAG_REFUSAL_INSUFFICIENT_EVIDENCE
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
                # Date-tag grounding check: a date tag not covered by any cited
                # chunk is the signature of a parametric answer dressed up as a
                # grounded one — replace it with a refusal rather than serve it.
                ungrounded_tags = find_ungrounded_date_tags(answer, retrieval["citations"])
                if ungrounded_tags:
                    logger.error(
                        "rag_query: answer discarded — ungrounded date tags "
                        f"{ungrounded_tags} not covered by any citation (query='{query[:120]}')"
                    )
                    answer = RAG_REFUSAL_INSUFFICIENT_EVIDENCE
                if trace:
                    trace.update(
                        output={RAG_TRACE_OUTPUT_ANSWER: answer},
                        metadata={
                            RAG_TRACE_META_REFUSAL: bool(ungrounded_tags),
                            RAG_TRACE_META_CITATION_COUNT: len(retrieval["citations"]),
                        },
                    )
                if not ungrounded_tags:
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
    podcast_slug: str | None = None,
    top_k: int | None = None,
    mmr_lambda: float | None = None,
    include_raw_messages: bool | None = None,
    unbounded_default_window: bool = False,
    session_id: str | None = None,
    user_id: str | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Run retrieval only — no LLM call. Returns reranked citations with source dates.

    `communities` optionally restricts retrieval to specific communities
    (data_source_name, e.g. ["langtalks"]); podcasts are excluded when set.

    `mmr_lambda` (0-1) optionally overrides the server default MMR relevance/
    diversity balance for this query; None falls back to the config default.

    `include_raw_messages` (parent-document retrieval): when true, each returned
    citation also carries the raw underlying messages behind that chunk
    (`parent_messages`). None falls back to the config default.

    `podcast_slug` optionally scopes retrieval to a single podcast tenant.
    """
    query = validate_query(query)
    top_k = clamp_top_k(top_k)
    ds = _parse_iso_date(date_start, "date_start")
    de = _parse_iso_date(date_end, "date_end")
    validate_date_range(ds, de)

    # OBS-1: when a per-key id is resolved (public SSE path), tag the trace with
    # it as user_id so the owner gets per-key analytics. Falls back to the legacy
    # user_id label (internal/stdio) when no key is resolved.
    trace, trace_id = create_rag_trace(
        name=RAGTraceName.MCP_SEARCH,
        user_id=key_id or user_id,
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
                podcast_slug=podcast_slug,
                rerank_top_k=top_k,
                mmr_lambda=mmr_lambda,
                include_raw_messages=include_raw_messages,
                unbounded_default_window=unbounded_default_window,
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


async def search_podcasts(
    query: str,
    podcast: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    top_k: int | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Search the podcast corpus and return dated, cited chunks (no LLM call).

    The frozen public retrieval tool. `podcast` is an OPTIONAL slug filter
    (e.g. "langtalks"); omitting it searches all podcasts. Retrieval is pinned to
    podcast-type content, so newsletters are never served on this surface. The
    caller's own agent composes the final answer from the returned chunks — the
    server does no generation, so there is $0 generation cost on this path.

    Returns the rag_search shape: citations (each with source_date_start/end),
    freshness_warning, oldest/newest source date, the applied date_filter, and
    the pinned sources.

    COST-1/COST-2/COST-4b: BEFORE any owner-paid embedding, the resolved per-key
    id is admission-checked (in-process rate limit + per-key daily quota) and the
    global daily embedding circuit breaker is consulted. A rejection is observed
    (OBS-2) and raised as a clean tool error with NO embedding call. F5: the
    podcast surface searches with an unbounded default window (evergreen corpus).
    """
    key_id = resolve_current_key_id()
    try:
        # Validate the slug at the tool boundary before it reaches the Mongo equality
        # filter (bounded, kebab-case) — it is public, adversarially-probed input.
        # rag_search additionally validates query/top_k/date-range; all raise
        # MCPToolInputError, caught below so a validation reject is observed (OBS-2).
        podcast = validate_podcast_slug(podcast)

        # Guards run only when a principal is resolved (public HTTP path). On
        # stdio / internal (no key record) the guards are skipped, preserving
        # behaviour. Anonymous (keyless) principals get their own tighter
        # admission stack; BOTH lanes then consume the shared embed breaker, so
        # total owner-paid embedding exposure stays bounded regardless of lane.
        if key_id is not None:
            if is_anonymous_key_id(key_id):
                await enforce_anonymous_admission(key_id, quota_repo=await _get_quota_repo())
            else:
                await enforce_query_admission(key_id, quota_repo=await _get_quota_repo())
            await check_global_embed_breaker()

        return await rag_search(
            query=query,
            date_start=date_start,
            date_end=date_end,
            sources=[str(ContentSourceType.PODCAST)],
            podcast_slug=podcast,
            top_k=top_k,
            unbounded_default_window=True,
            session_id=session_id,
            user_id=user_id,
            key_id=key_id,
        )
    except QueryAdmissionError as e:
        emit_reject(reason=e.reason, key_id=key_id, tool=MCP_TOOL_SEARCH_PODCASTS)
        raise
    except MCPToolInputError:
        # Boundary-validation reject (over-long query, bad top_k, bad dates, bad
        # slug): surface it on the abuse-detection signal, then re-raise unchanged.
        emit_reject(reason=RAG_REJECT_REASON_VALIDATION, key_id=key_id, tool=MCP_TOOL_SEARCH_PODCASTS)
        raise


async def list_podcasts() -> dict[str, list[dict[str, Any]]]:
    """List the podcasts available to query (the discovery tool).

    Reads the `podcasts` catalog (active rows only) and joins each row with its
    per-podcast chunk stats (chunk count, earliest/latest source date). A new
    podcast appears here the moment its catalog row is added — zero client
    change. Returns {"podcasts": [ {slug, title, description, chunk_count,
    source_date_start, source_date_end}, ... ]}.
    """
    db = await get_database()
    catalog = PodcastsRepository(db)
    chunks_repo = ChunksRepository(db)

    active = await catalog.list_active()

    stats_pipeline = [
        {"$match": {RAGChunkKeys.CONTENT_SOURCE: str(ContentSourceType.PODCAST)}},
        {
            "$group": {
                "_id": f"${RAGChunkKeys.PODCAST_SLUG}",
                "chunk_count": {"$sum": 1},
                "source_date_start": {"$min": f"${RAGChunkKeys.SOURCE_DATE_START}"},
                "source_date_end": {"$max": f"${RAGChunkKeys.SOURCE_DATE_END}"},
            }
        },
    ]
    stats_by_slug: dict[str, dict[str, Any]] = {}
    cursor = await chunks_repo.collection.aggregate(stats_pipeline)
    async for doc in cursor:
        stats_by_slug[doc["_id"]] = doc

    podcasts: list[dict[str, Any]] = []
    for row in active:
        slug = row[PodcastCatalogKeys.SLUG]
        stats = stats_by_slug.get(slug, {})
        podcasts.append(
            {
                "slug": slug,
                "title": row.get(PodcastCatalogKeys.TITLE),
                "description": row.get(PodcastCatalogKeys.DESCRIPTION),
                "chunk_count": stats.get("chunk_count", 0),
                "source_date_start": _iso_or_none(stats.get("source_date_start")),
                "source_date_end": _iso_or_none(stats.get("source_date_end")),
            }
        )

    return {"podcasts": podcasts}


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
