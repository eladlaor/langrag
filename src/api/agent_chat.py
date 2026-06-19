"""FastAPI router for the agentic chatbot.

v1.13.0 ships the non-streaming endpoints (`/agent/sessions`,
`/agent/chat`, plus session listing + memory inspection). v1.13.0
streaming endpoints (`/agent/chat/stream`, `/agent/chat/resume`) land
in commit 8. The frontend lands in v1.14.0 (commit 9).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.auth.dependencies import require_user
from agent.auth.user_context import UserContext, user_context
from agent.runtime import get_agent_graph, get_agent_store
from constants import (
    AgentEventType,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
)
from custom_types.db_schemas import MemoryNamespace
from db.connection import get_database
from db.repositories.agent_sessions import AgentSessionsRepository
from db.repositories.users import UsersRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ----------------------------------------------------------------------
# Request / response schemas
# ----------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    title: str = Field(default="", description="Optional session title.")
    community_context: str | None = Field(
        default=None, description="Default community key for this session."
    )


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str
    title: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Session id from POST /agent/sessions.")
    message: str = Field(..., min_length=1, description="The user's turn.")


class ResumeRequest(BaseModel):
    """Body for POST /agent/chat/resume — resuming after a HITL interrupt.

    The frontend pops a confirm dialog when it sees an `interrupt_required`
    SSE event; on user click it POSTs to this endpoint with the same
    `session_id` plus a `decision` ("approve" or "reject"). The agent
    graph resumes from its last checkpoint with the decision as input.
    """

    session_id: str = Field(..., description="Session id whose interrupted graph to resume.")
    decision: str = Field(..., description='"approve" or "reject" (or any tool-specific payload).')


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    artifact_events: list[dict[str, Any]] = Field(default_factory=list)
    memories_loaded: int = 0


class SessionSummary(BaseModel):
    session_id: str
    title: str
    community_context: str | None
    created_at: str
    last_message_at: str
    message_count: int


class MemoryItem(BaseModel):
    memory_id: str
    namespace: str
    content: str
    importance: float


class RagPreferencesResponse(BaseModel):
    """The caller's saved RAG retrieval preferences (or config-backed defaults)."""

    mmr_lambda: float = Field(..., description="MMR relevance/diversity weight (0-1).")
    enable_mmr_diversity: bool = Field(..., description="Whether MMR diversity reranking is applied.")


class RagPreferencesUpdate(BaseModel):
    """Body for PUT /agent/rag-preferences. Validated at the API boundary so an
    out-of-range lambda returns 422 before any DB write."""

    mmr_lambda: float = Field(..., ge=0.0, le=1.0, description="MMR relevance/diversity weight (0-1).")
    enable_mmr_diversity: bool = Field(..., description="Whether MMR diversity reranking is applied.")


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    user: UserContext = Depends(require_user),
) -> CreateSessionResponse:
    """Create a new agent session bound to the authenticated user."""
    db = await get_database()
    repo = AgentSessionsRepository(db)
    session_id = await repo.create_session(
        user_id=user.user_id,
        title=payload.title,
        community_context=payload.community_context,
    )
    row = await repo.find_by_session_id(session_id)
    if row is None:  # pragma: no cover — defensive
        raise HTTPException(
            status_code=HTTP_STATUS_INTERNAL_SERVER_ERROR,
            detail="Failed to create session.",
        )
    return CreateSessionResponse(
        session_id=session_id,
        created_at=_iso(row.get("created_at")),
        title=row.get("title", ""),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: UserContext = Depends(require_user),
) -> ChatResponse:
    """Run a single non-streaming agent turn against an existing session."""
    db = await get_database()
    sessions = AgentSessionsRepository(db)
    session_row = await sessions.find_by_session_id(payload.session_id)
    if session_row is None or session_row.get("user_id") != user.user_id:
        # Don't reveal whether the session belongs to a different user.
        raise HTTPException(status_code=404, detail="Session not found.")

    graph = await get_agent_graph()
    await get_agent_store()  # Eager-init so a first-turn cold start is observable.

    config = {
        "configurable": {
            "thread_id": payload.session_id,
            "user_id": user.user_id,
            "communities": list(user.communities),
        }
    }
    new_messages = [HumanMessage(content=payload.message)]

    with user_context(user):
        result = await graph.ainvoke(
            {"messages": new_messages},
            config=config,
        )

    # Find the most recent assistant message (the LLM's final reply).
    messages = result.get("messages", [])
    assistant_content = ""
    tool_calls: list[dict[str, Any]] = []
    for m in reversed(messages):
        if getattr(m, "type", "") == "ai":
            if getattr(m, "tool_calls", None):
                # The very last message is a pre-tool-call AI message;
                # skip it and keep looking for the final, post-tool reply.
                tool_calls = [_serialize_tool_call(tc) for tc in m.tool_calls]
                continue
            assistant_content = _coerce_content(m.content)
            break

    await sessions.touch_session(payload.session_id)

    return ChatResponse(
        session_id=payload.session_id,
        assistant_message=assistant_content,
        tool_calls=tool_calls,
        artifact_events=list(result.get("artifact_events", [])),
        memories_loaded=len(result.get("retrieved_memories", [])),
    )


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    user: UserContext = Depends(require_user),
    limit: int = 50,
) -> list[SessionSummary]:
    """List the authenticated user's sessions, newest activity first."""
    db = await get_database()
    repo = AgentSessionsRepository(db)
    rows = await repo.find_for_user(user.user_id, limit=limit)
    return [
        SessionSummary(
            session_id=r.get("session_id", ""),
            title=r.get("title", ""),
            community_context=r.get("community_context"),
            created_at=_iso(r.get("created_at")),
            last_message_at=_iso(r.get("last_message_at")),
            message_count=int(r.get("message_count", 0) or 0),
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
async def delete_session(
    session_id: str,
    user: UserContext = Depends(require_user),
) -> Response:
    """Delete a session. User-scoped — cross-tenant 404s identically."""
    db = await get_database()
    repo = AgentSessionsRepository(db)
    row = await repo.find_by_session_id(session_id)
    if row is None or row.get("user_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    await repo.delete_session(session_id)
    return Response(status_code=204)


@router.get("/memories", response_model=list[MemoryItem])
async def list_memories_endpoint(
    namespace: str | None = None,
    limit: int = 100,
    user: UserContext = Depends(require_user),
) -> list[MemoryItem]:
    """List the authenticated user's long-term memories (GDPR / trust panel)."""
    if namespace is not None:
        try:
            ns = MemoryNamespace(namespace.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown namespace {namespace!r}. "
                f"Valid: {[str(n) for n in MemoryNamespace]}",
            )
        prefix = (user.user_id, str(ns))
    else:
        prefix = (user.user_id,)

    store = await get_agent_store()
    items = await store.asearch(prefix, query=None, limit=limit)
    return [
        MemoryItem(
            memory_id=item.key,
            namespace=item.namespace[1] if len(item.namespace) > 1 else "",
            content=(item.value or {}).get("content", ""),
            importance=float((item.value or {}).get("importance", 0.5)),
        )
        for item in items
    ]


@router.delete("/memories/{memory_id}", status_code=204, response_class=Response)
async def delete_memory_endpoint(
    memory_id: str,
    user: UserContext = Depends(require_user),
) -> Response:
    """GDPR forget endpoint. User-scoped at the store level."""
    store = await get_agent_store()
    # Try all three namespaces; store enforces user_id scoping internally.
    for ns in MemoryNamespace:
        await store.adelete((user.user_id, str(ns)), memory_id)
    return Response(status_code=204)


@router.get("/rag-preferences", response_model=RagPreferencesResponse)
async def get_rag_preferences(
    user: UserContext = Depends(require_user),
) -> RagPreferencesResponse:
    """Return the caller's saved RAG preferences, or config-backed defaults."""
    db = await get_database()
    repo = UsersRepository(db)
    prefs = await repo.get_rag_preferences(user.user_id)
    return RagPreferencesResponse(
        mmr_lambda=prefs.mmr_lambda,
        enable_mmr_diversity=prefs.enable_mmr_diversity,
    )


@router.put("/rag-preferences", response_model=RagPreferencesResponse)
async def put_rag_preferences(
    payload: RagPreferencesUpdate,
    user: UserContext = Depends(require_user),
) -> RagPreferencesResponse:
    """Persist the caller's RAG preferences and echo the stored value back."""
    db = await get_database()
    repo = UsersRepository(db)
    prefs = await repo.set_rag_preferences(
        user_id=user.user_id,
        mmr_lambda=payload.mmr_lambda,
        enable_mmr_diversity=payload.enable_mmr_diversity,
    )
    return RagPreferencesResponse(
        mmr_lambda=prefs.mmr_lambda,
        enable_mmr_diversity=prefs.enable_mmr_diversity,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    user: UserContext = Depends(require_user),
) -> StreamingResponse:
    """SSE-streaming agent turn.

    Emits events from the taxonomy declared in `AgentEventType`:
      - `tool_call_started` / `tool_call_finished` around each tool call
      - `token` for each chunk of the final assistant reply
      - `error` on any failure
      - `done` at the end of the turn
    """
    return StreamingResponse(
        _event_stream(payload, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/resume")
async def chat_resume(
    payload: ResumeRequest,
    user: UserContext = Depends(require_user),
) -> StreamingResponse:
    """Resume a turn previously paused by `interrupt()`.

    Posts `Command(resume=decision)` to the graph at the checkpoint
    where it interrupted. Streams the continuation just like a normal
    turn. HITL gating proper ships in commit 10; the resume endpoint is
    here so the SSE event taxonomy and the round-trip protocol are
    locked in.
    """
    return StreamingResponse(
        _event_stream_resume(payload, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _sse(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


async def _validate_session(user: UserContext, session_id: str):
    db = await get_database()
    sessions = AgentSessionsRepository(db)
    row = await sessions.find_by_session_id(session_id)
    if row is None or row.get("user_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return sessions


async def _event_stream(payload: ChatRequest, user: UserContext) -> AsyncIterator[str]:
    """Drive a single agent turn and serialize the state-update stream to SSE."""
    try:
        sessions = await _validate_session(user, payload.session_id)
    except HTTPException as e:
        yield _sse(AgentEventType.ERROR, {"error": e.detail, "status_code": e.status_code})
        return

    try:
        graph = await get_agent_graph()
        await get_agent_store()
    except Exception as e:  # pragma: no cover — runtime build failure
        logger.exception("agent runtime build failed")
        yield _sse(AgentEventType.ERROR, {"error": f"agent runtime unavailable: {e}"})
        return

    config = {
        "configurable": {
            "thread_id": payload.session_id,
            "user_id": user.user_id,
            "communities": list(user.communities),
        }
    }
    new_messages = [HumanMessage(content=payload.message)]

    tool_started_ids: set[str] = set()
    final_text = ""

    try:
        with user_context(user):
            async for stream_chunk in graph.astream(
                {"messages": new_messages},
                config=config,
                stream_mode="updates",
            ):
                # Each chunk is {node_name: state_update_dict}.
                for node, update in stream_chunk.items():
                    if not isinstance(update, dict):
                        continue
                    msgs = update.get("messages") or []
                    for m in msgs:
                        async for evt in _emit_for_message(m, tool_started_ids):
                            yield evt
                    # Surface any new artifact_panel events the graph appended.
                    for art in update.get("artifact_events") or []:
                        yield _sse(AgentEventType.ARTIFACT_PANEL, art)
                    # Surface any interrupt the graph raised explicitly.
                    pending = update.get("pending_interrupt")
                    if pending:
                        yield _sse(AgentEventType.INTERRUPT_REQUIRED, pending)
            # Pull the final state once the stream ends so we can flush
            # any trailing assistant text we haven't emitted yet (some
            # LLM clients deliver the full reply in one chunk, which the
            # `updates` stream surfaces as a single AIMessage).
            final_text = ""  # tokens already emitted per message

        await sessions.touch_session(payload.session_id)
        yield _sse(
            AgentEventType.DONE,
            {"session_id": payload.session_id},
        )
    except Exception as e:
        logger.exception("agent stream failed: session_id=%s", payload.session_id)
        yield _sse(AgentEventType.ERROR, {"error": str(e)})


async def _event_stream_resume(
    payload: ResumeRequest, user: UserContext
) -> AsyncIterator[str]:
    """Resume an interrupted turn with `Command(resume=...)`."""
    try:
        sessions = await _validate_session(user, payload.session_id)
    except HTTPException as e:
        yield _sse(AgentEventType.ERROR, {"error": e.detail, "status_code": e.status_code})
        return

    try:
        graph = await get_agent_graph()
        await get_agent_store()
    except Exception as e:  # pragma: no cover
        yield _sse(AgentEventType.ERROR, {"error": f"agent runtime unavailable: {e}"})
        return

    config = {
        "configurable": {
            "thread_id": payload.session_id,
            "user_id": user.user_id,
            "communities": list(user.communities),
        }
    }

    tool_started_ids: set[str] = set()
    try:
        with user_context(user):
            async for stream_chunk in graph.astream(
                Command(resume=payload.decision),
                config=config,
                stream_mode="updates",
            ):
                for node, update in stream_chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for m in update.get("messages") or []:
                        async for evt in _emit_for_message(m, tool_started_ids):
                            yield evt
        await sessions.touch_session(payload.session_id)
        yield _sse(AgentEventType.DONE, {"session_id": payload.session_id})
    except Exception as e:
        logger.exception(
            "agent resume stream failed: session_id=%s", payload.session_id
        )
        yield _sse(AgentEventType.ERROR, {"error": str(e)})


async def _emit_for_message(
    m: Any, tool_started_ids: set[str]
) -> AsyncIterator[str]:
    """Translate one graph-emitted message into one or more SSE events."""
    if isinstance(m, AIMessage):
        tool_calls = getattr(m, "tool_calls", None) or []
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id in tool_started_ids:
                    continue
                tool_started_ids.add(tc_id)
                yield _sse(
                    AgentEventType.TOOL_CALL_STARTED,
                    {"call_id": tc_id, "tool": name, "args": _redact_args(args)},
                )
        else:
            text = _coerce_content(m.content)
            if text:
                yield _sse(AgentEventType.TOKEN, {"token": text})
    elif isinstance(m, ToolMessage):
        yield _sse(
            AgentEventType.TOOL_CALL_FINISHED,
            {
                "call_id": getattr(m, "tool_call_id", ""),
                "tool": getattr(m, "name", ""),
                "status": getattr(m, "status", "success"),
                "result_summary": _coerce_content(m.content)[:280],
            },
        )


def _redact_args(args: Any) -> Any:
    """Best-effort redaction: truncate long string values so the SSE
    chip render doesn't ship a 50KB blob to the browser."""
    if not isinstance(args, dict):
        return args
    redacted: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            redacted[k] = v[:200] + "…"
        else:
            redacted[k] = v
    return redacted


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _coerce_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _serialize_tool_call(tc: Any) -> dict[str, Any]:
    if isinstance(tc, dict):
        return {"name": tc.get("name"), "args": tc.get("args", {}), "id": tc.get("id")}
    return {
        "name": getattr(tc, "name", ""),
        "args": getattr(tc, "args", {}),
        "id": getattr(tc, "id", ""),
    }
