"""
RAG Conversation API Router

FastAPI endpoints for RAG chat, session management, podcast ingestion, and evaluations.
All chat / search / sources endpoints accept optional date_start / date_end so callers
can scope retrieval to a window. Public endpoints are gated by the API key dependency
and rate-limited via slowapi when enabled in config.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from constants import (
    CONTENT_TYPE_EVENT_STREAM,
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    HTTP_STATUS_NOT_FOUND,
    RAGEventType,
    RAG_RATE_LIMIT_CHAT,
    RAG_RATE_LIMIT_DEFAULT,
    RAG_RATE_LIMIT_INGEST,
    ROUTE_RAG_CHAT,
    ROUTE_RAG_CHAT_STREAM,
    ROUTE_RAG_EVALUATIONS,
    ROUTE_RAG_INGEST_NEWSLETTERS,
    ROUTE_RAG_INGEST_PODCASTS,
    ROUTE_RAG_INGEST_PODCASTS_SCAN,
    ROUTE_RAG_SESSIONS,
    ROUTE_RAG_SESSION_BY_ID,
    ROUTE_RAG_SOURCES_NEWSLETTERS,
    ROUTE_RAG_SOURCES_STATS,
    ContentSourceType,
)
from custom_types.api_schemas import (
    RAGChatRequest,
    RAGChatResponse,
    RAGCitationResponse,
    RAGEvaluationResponse,
    RAGNewsletterIngestRequest,
    RAGPodcastIngestRequest,
    RAGSessionCreateRequest,
    RAGSessionResponse,
    RAGSourceStats,
)
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from db.repositories.rag_evaluations import EvaluationsRepository
from rag.auth.dependencies import require_api_key
from rag.auth.rate_limit import limiter
from rag.conversation.manager import ConversationManager
from rag.generation.rag_chain import generate_answer, generate_answer_stream
from rag.retrieval.pipeline import RetrievalPipeline
from rag.sources.podcast_source import PODCAST_DATA_DIR, SUPPORTED_AUDIO_EXTENSIONS, PodcastSource

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_date(value: str | None, label: str) -> datetime | None:
    """Parse YYYY-MM-DD or ISO 8601 into a UTC-aware datetime; raise 400 on invalid."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTP_STATUS_BAD_REQUEST,
            detail=f"Invalid {label}: '{value}'. Expected YYYY-MM-DD or ISO 8601.",
        ) from e
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _citation_to_response(c: dict) -> RAGCitationResponse:
    """Map a citation dict from the retrieval pipeline into the API response model."""
    return RAGCitationResponse(
        index=c.get("index", 0),
        chunk_id=c.get("chunk_id", ""),
        source_type=c.get("source_type", ""),
        source_title=c.get("source_title", ""),
        source_date_start=c.get("source_date_start") or "",
        source_date_end=c.get("source_date_end") or "",
        snippet=c.get("snippet", ""),
        search_score=c.get("search_score", 0.0),
        metadata=c.get("metadata", {}),
    )


def _iso_date_or_none(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


# ============================================================================
# STREAMING CHAT
# ============================================================================


@router.post(ROUTE_RAG_CHAT_STREAM, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_CHAT)
async def rag_chat_stream(request: Request, body: RAGChatRequest):
    """SSE streaming chat endpoint with optional date-range scoping."""
    manager = ConversationManager()

    session_id = body.session_id
    if not session_id:
        session_id = await manager.create_session(body.content_sources)

    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")

    await manager.add_user_message(session_id, body.query)
    history = await manager.get_conversation_history(session_id)

    date_start = _parse_date(body.date_start, "date_start")
    date_end = _parse_date(body.date_end, "date_end")

    async def event_stream():
        try:
            pipeline = RetrievalPipeline()
            retrieval_result = await pipeline.retrieve(
                query=body.query,
                content_sources=body.content_sources or None,
                date_start=date_start,
                date_end=date_end,
            )

            context = retrieval_result["context"]
            citations = retrieval_result["citations"]

            full_answer = ""
            async for token in generate_answer_stream(
                query=body.query,
                context=context,
                conversation_history=history,
                date_start=date_start,
                date_end=date_end,
                freshness_warning=retrieval_result["freshness_warning"],
                newest_source_date=retrieval_result["newest_source_date"],
            ):
                full_answer += token
                yield f"event: {RAGEventType.TOKEN}\ndata: {json.dumps({'token': token})}\n\n"

            for citation in citations:
                yield f"event: {RAGEventType.CITATION}\ndata: {json.dumps(citation, default=str)}\n\n"

            message_id = await manager.add_assistant_message(
                session_id=session_id,
                content=full_answer,
                citations=citations,
            )

            done_payload = {
                "session_id": session_id,
                "message_id": message_id,
                "freshness_warning": retrieval_result["freshness_warning"],
                "oldest_source_date": _iso_date_or_none(retrieval_result["oldest_source_date"]),
                "newest_source_date": _iso_date_or_none(retrieval_result["newest_source_date"]),
            }
            yield f"event: {RAGEventType.DONE}\ndata: {json.dumps(done_payload, default=str)}\n\n"

        except Exception as e:
            logger.error(f"RAG chat stream error: {e}", extra={"session_id": session_id})
            yield f"event: {RAGEventType.ERROR}\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type=CONTENT_TYPE_EVENT_STREAM,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================


@router.post(ROUTE_RAG_SESSIONS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def create_session(request: Request, body: RAGSessionCreateRequest) -> RAGSessionResponse:
    """Create a new conversation session."""
    manager = ConversationManager()
    session_id = await manager.create_session(
        content_sources=body.content_sources,
        title=body.title,
    )
    return RAGSessionResponse(
        session_id=session_id,
        content_sources=body.content_sources,
        title=body.title,
    )


@router.get(ROUTE_RAG_SESSIONS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def list_sessions(request: Request, limit: int = 20, skip: int = 0) -> list[RAGSessionResponse]:
    """List conversation sessions (most recent first)."""
    manager = ConversationManager()
    sessions = await manager.list_sessions(limit=limit, skip=skip)
    return [
        RAGSessionResponse(
            session_id=s.get("session_id", ""),
            title=s.get("title"),
            content_sources=s.get("content_sources", []),
            created_at=str(s.get("created_at", "")),
            updated_at=str(s.get("updated_at", "")),
            message_count=s.get("message_count", 0),
        )
        for s in sessions
    ]


@router.get(ROUTE_RAG_SESSION_BY_ID, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def get_session(request: Request, session_id: str):
    """Get a session with full message history."""
    manager = ConversationManager()
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")
    session.pop("_id", None)
    return session


@router.delete(ROUTE_RAG_SESSION_BY_ID, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def delete_session(request: Request, session_id: str):
    """Delete a conversation session."""
    manager = ConversationManager()
    deleted = await manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")
    return {"message": f"Session {session_id} deleted"}


# ============================================================================
# PODCAST INGESTION
# ============================================================================


@router.post(ROUTE_RAG_INGEST_PODCASTS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_INGEST)
async def ingest_podcast(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(None),
    episode_date: str = Form(None),
):
    """
    Upload and ingest a podcast audio file.

    Filename should start with YYYY-MM-DD; otherwise pass episode_date explicitly
    (or include the file in data/podcasts/manifest.json before scanning).
    """
    if not file.filename:
        raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail="No filename provided")

    safe_name = PurePosixPath(file.filename).name
    if not safe_name:
        raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail="Invalid filename")

    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_STATUS_BAD_REQUEST,
            detail=f"Unsupported audio format: {ext}. Supported: {SUPPORTED_AUDIO_EXTENSIONS}",
        )

    PODCAST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = PODCAST_DATA_DIR / safe_name
    content = await file.read()
    await asyncio.to_thread(file_path.write_bytes, content)

    logger.info(f"Saved uploaded podcast: {file_path}")

    try:
        from rag.ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline()
        source = PodcastSource()
        kwargs = {"title": title or file_path.stem}
        if episode_date:
            kwargs["episode_date"] = episode_date
        result = await pipeline.ingest(
            source=source,
            source_id=str(file_path),
            **kwargs,
        )
        return result
    except Exception as e:
        logger.error(f"Podcast ingestion failed: {e}", extra={"filename": file.filename})
        raise HTTPException(status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(ROUTE_RAG_INGEST_PODCASTS_SCAN, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_INGEST)
async def scan_and_ingest_podcasts(request: Request, body: RAGPodcastIngestRequest = RAGPodcastIngestRequest()):
    """Scan data/podcasts/ and ingest any new audio files."""
    source = PodcastSource()
    available = await source.list_sources()

    if not available:
        return {"message": "No audio files found in data/podcasts/", "results": []}

    from rag.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline()
    results = await pipeline.ingest_batch(
        source=source,
        source_ids=[s["source_id"] for s in available],
        force_refresh=body.force_refresh,
    )
    return {"message": f"Processed {len(results)} audio files", "results": results}


# ============================================================================
# SOURCE STATS
# ============================================================================


@router.get(ROUTE_RAG_SOURCES_STATS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def get_source_stats(request: Request) -> list[RAGSourceStats]:
    """Get chunk counts per content source type."""
    db = await get_database()
    repo = ChunksRepository(db)
    stats = await repo.count_by_source_type()
    return [
        RAGSourceStats(source_type=source_type, chunk_count=count)
        for source_type, count in stats.items()
    ]


# ============================================================================
# NON-STREAMING CHAT (CLI / Agent-friendly)
# ============================================================================


@router.post(ROUTE_RAG_CHAT, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_CHAT)
async def rag_chat(request: Request, body: RAGChatRequest) -> RAGChatResponse:
    """Non-streaming chat endpoint with optional date-range scoping."""
    manager = ConversationManager()

    session_id = body.session_id
    if not session_id:
        session_id = await manager.create_session(body.content_sources)

    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")

    await manager.add_user_message(session_id, body.query)
    history = await manager.get_conversation_history(session_id)

    date_start = _parse_date(body.date_start, "date_start")
    date_end = _parse_date(body.date_end, "date_end")

    try:
        pipeline = RetrievalPipeline()
        retrieval_result = await pipeline.retrieve(
            query=body.query,
            content_sources=body.content_sources or None,
            date_start=date_start,
            date_end=date_end,
        )

        context = retrieval_result["context"]
        citations = retrieval_result["citations"]

        answer = await generate_answer(
            query=body.query,
            context=context,
            conversation_history=history,
            date_start=date_start,
            date_end=date_end,
            freshness_warning=retrieval_result["freshness_warning"],
            newest_source_date=retrieval_result["newest_source_date"],
        )

        await manager.add_assistant_message(
            session_id=session_id,
            content=answer,
            citations=citations,
        )

        return RAGChatResponse(
            session_id=session_id,
            answer=answer,
            citations=[_citation_to_response(c) for c in citations],
            freshness_warning=retrieval_result["freshness_warning"],
            oldest_source_date=_iso_date_or_none(retrieval_result["oldest_source_date"]),
            newest_source_date=_iso_date_or_none(retrieval_result["newest_source_date"]),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RAG chat error: {e}", extra={"session_id": session_id})
        raise HTTPException(status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# NEWSLETTER INGESTION
# ============================================================================


@router.post(ROUTE_RAG_INGEST_NEWSLETTERS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_INGEST)
async def ingest_newsletters(request: Request, body: RAGNewsletterIngestRequest):
    """Ingest newsletters from MongoDB into RAG chunks."""
    try:
        from rag.ingestion.pipeline import IngestionPipeline
        from rag.sources.newsletter_source import NewsletterSource

        source = NewsletterSource()
        newsletters = await source.list_sources_filtered(
            data_source_name=body.data_source_name,
            limit=body.limit,
            start_date=body.start_date,
            end_date=body.end_date,
        )

        if not newsletters:
            return {
                "message": "No newsletters found matching filters",
                "ingested_count": 0,
                "skipped_count": 0,
                "total_chunks": 0,
            }

        pipeline = IngestionPipeline()
        results = await pipeline.ingest_batch(
            source=source,
            source_ids=[nl["source_id"] for nl in newsletters],
            force_refresh=body.force_refresh,
        )

        ingested_count = sum(1 for r in results if not r.get("skipped") and not r.get("error"))
        skipped_count = sum(1 for r in results if r.get("skipped"))
        total_chunks = sum(r.get("chunks_stored", 0) for r in results)

        return {
            "message": f"Processed {len(results)} newsletters",
            "ingested_count": ingested_count,
            "skipped_count": skipped_count,
            "total_chunks": total_chunks,
            "results": results,
        }

    except Exception as e:
        logger.error(f"Newsletter ingestion failed: {e}")
        raise HTTPException(status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(ROUTE_RAG_SOURCES_NEWSLETTERS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def list_newsletter_sources(request: Request):
    """List ingested newsletters with metadata."""
    try:
        db = await get_database()
        repo = ChunksRepository(db)
        ingested = await repo.list_ingested_sources(str(ContentSourceType.NEWSLETTER))
        return ingested
    except Exception as e:
        logger.error(f"Failed to list newsletter sources: {e}")
        raise HTTPException(status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# EVALUATIONS
# ============================================================================


@router.get(ROUTE_RAG_EVALUATIONS, dependencies=[Depends(require_api_key)])
@limiter.limit(RAG_RATE_LIMIT_DEFAULT)
async def get_evaluations(request: Request, session_id: str) -> list[RAGEvaluationResponse]:
    """Get evaluation scores for a session."""
    db = await get_database()
    repo = EvaluationsRepository(db)
    evaluations = await repo.get_session_evaluations(session_id)
    return [
        RAGEvaluationResponse(
            evaluation_id=e.get("evaluation_id", ""),
            session_id=e.get("session_id", ""),
            scores=e.get("scores", {}),
            overall_passed=e.get("overall_passed", False),
            status=e.get("status", "pending"),
            duration_ms=e.get("evaluation_duration_ms", 0),
        )
        for e in evaluations
    ]
