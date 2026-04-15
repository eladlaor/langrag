"""
RAG Conversation API Router

FastAPI endpoints for RAG chat, session management, podcast ingestion, and evaluations.
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from constants import (
    CONTENT_TYPE_EVENT_STREAM,
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NOT_FOUND,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    ROUTE_RAG_CHAT_STREAM,
    ROUTE_RAG_SESSIONS,
    ROUTE_RAG_SESSION_BY_ID,
    ROUTE_RAG_INGEST_PODCASTS,
    ROUTE_RAG_INGEST_PODCASTS_SCAN,
    ROUTE_RAG_SOURCES_STATS,
    ROUTE_RAG_EVALUATIONS,
    RAGEventType,
    ContentSourceType,
)
from custom_types.api_schemas import (
    RAGChatRequest,
    RAGSessionCreateRequest,
    RAGSessionResponse,
    RAGPodcastIngestRequest,
    RAGSourceStats,
    RAGEvaluationResponse,
)
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from db.repositories.rag_evaluations import EvaluationsRepository
from rag.conversation.manager import ConversationManager
from rag.generation.rag_chain import generate_answer_stream
from rag.retrieval.pipeline import RetrievalPipeline
from rag.sources.podcast_source import PodcastSource, PODCAST_DATA_DIR, SUPPORTED_AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# STREAMING CHAT
# ============================================================================


@router.post(ROUTE_RAG_CHAT_STREAM)
async def rag_chat_stream(request: RAGChatRequest):
    """
    SSE streaming chat endpoint.

    Creates or reuses a session, retrieves relevant context,
    and streams the answer token-by-token via SSE.
    """
    manager = ConversationManager()

    # Create or reuse session
    session_id = request.session_id
    if not session_id:
        session_id = await manager.create_session(request.content_sources)

    # Verify session exists
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")

    # Record user message
    await manager.add_user_message(session_id, request.query)

    # Get conversation history
    history = await manager.get_conversation_history(session_id)

    async def event_stream():
        try:
            # Retrieve context
            pipeline = RetrievalPipeline()
            retrieval_result = await pipeline.retrieve(
                query=request.query,
                content_sources=request.content_sources or None,
            )

            context = retrieval_result["context"]
            citations = retrieval_result["citations"]

            # Stream answer tokens
            full_answer = ""
            async for token in generate_answer_stream(
                query=request.query,
                context=context,
                conversation_history=history,
            ):
                full_answer += token
                yield f"event: {RAGEventType.TOKEN}\ndata: {json.dumps({'token': token})}\n\n"

            # Send citations
            for citation in citations:
                yield f"event: {RAGEventType.CITATION}\ndata: {json.dumps(citation)}\n\n"

            # Record assistant message
            message_id = await manager.add_assistant_message(
                session_id=session_id,
                content=full_answer,
                citations=citations,
            )

            # Done event
            yield f"event: {RAGEventType.DONE}\ndata: {json.dumps({'session_id': session_id, 'message_id': message_id})}\n\n"

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


@router.post(ROUTE_RAG_SESSIONS)
async def create_session(request: RAGSessionCreateRequest) -> RAGSessionResponse:
    """Create a new conversation session."""
    manager = ConversationManager()
    session_id = await manager.create_session(
        content_sources=request.content_sources,
        title=request.title,
    )
    return RAGSessionResponse(
        session_id=session_id,
        content_sources=request.content_sources,
        title=request.title,
    )


@router.get(ROUTE_RAG_SESSIONS)
async def list_sessions(limit: int = 20, skip: int = 0) -> list[RAGSessionResponse]:
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


@router.get(ROUTE_RAG_SESSION_BY_ID)
async def get_session(session_id: str):
    """Get a session with full message history."""
    manager = ConversationManager()
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")
    session.pop("_id", None)
    return session


@router.delete(ROUTE_RAG_SESSION_BY_ID)
async def delete_session(session_id: str):
    """Delete a conversation session."""
    manager = ConversationManager()
    deleted = await manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=f"Session not found: {session_id}")
    return {"message": f"Session {session_id} deleted"}


# ============================================================================
# PODCAST INGESTION
# ============================================================================


@router.post(ROUTE_RAG_INGEST_PODCASTS)
async def ingest_podcast(
    file: UploadFile = File(...),
    title: str = Form(None),
):
    """
    Upload and ingest a podcast audio file.

    Saves to data/podcasts/, transcribes, chunks, embeds, and stores.
    """
    if not file.filename:
        raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail="No filename provided")

    # Sanitize filename to prevent path traversal
    safe_name = PurePosixPath(file.filename).name
    if not safe_name:
        raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail="Invalid filename")

    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_STATUS_BAD_REQUEST,
            detail=f"Unsupported audio format: {ext}. Supported: {SUPPORTED_AUDIO_EXTENSIONS}",
        )

    # Save uploaded file
    PODCAST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = PODCAST_DATA_DIR / safe_name
    content = await file.read()
    await asyncio.to_thread(file_path.write_bytes, content)

    logger.info(f"Saved uploaded podcast: {file_path}")

    # Ingest
    try:
        from rag.ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline()
        source = PodcastSource()
        result = await pipeline.ingest(
            source=source,
            source_id=str(file_path),
            title=title or file_path.stem,
        )
        return result
    except Exception as e:
        logger.error(f"Podcast ingestion failed: {e}", extra={"filename": file.filename})
        raise HTTPException(status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(ROUTE_RAG_INGEST_PODCASTS_SCAN)
async def scan_and_ingest_podcasts(request: RAGPodcastIngestRequest = RAGPodcastIngestRequest()):
    """
    Scan data/podcasts/ directory and ingest any new audio files.
    """
    source = PodcastSource()
    available = await source.list_sources()

    if not available:
        return {"message": "No audio files found in data/podcasts/", "results": []}

    from rag.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline()
    results = await pipeline.ingest_batch(
        source=source,
        source_ids=[s["source_id"] for s in available],
        force_refresh=request.force_refresh,
    )
    return {"message": f"Processed {len(results)} audio files", "results": results}


# ============================================================================
# SOURCE STATS
# ============================================================================


@router.get(ROUTE_RAG_SOURCES_STATS)
async def get_source_stats() -> list[RAGSourceStats]:
    """Get chunk counts per content source type."""
    db = await get_database()
    repo = ChunksRepository(db)
    stats = await repo.count_by_source_type()
    return [
        RAGSourceStats(source_type=source_type, chunk_count=count)
        for source_type, count in stats.items()
    ]


# ============================================================================
# EVALUATIONS
# ============================================================================


@router.get(ROUTE_RAG_EVALUATIONS)
async def get_evaluations(session_id: str) -> list[RAGEvaluationResponse]:
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
