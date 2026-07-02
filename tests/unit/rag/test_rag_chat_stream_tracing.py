"""Unit tests: the streaming rag_chat_stream handler creates its trace in the
OUTER scope (before returning the StreamingResponse), threads trace_id into
retrieval, attaches a callback to streamed generation, flushes AFTER the DONE
event, flags refusal + skips eval on empty context, and still flushes when the
stream errors mid-flight. Deps mocked so it runs without Docker/network."""

from unittest.mock import AsyncMock, MagicMock, patch

from api import rag_conversation
from constants import RAGEventType, RAG_TRACE_META_REFUSAL
from custom_types.api_schemas import RAGChatRequest
from custom_types.field_keys import RAGApiKeyKeys

_KEY_RECORD = {RAGApiKeyKeys.OWNER: "owner-1"}
_SENTINEL = object()


def _fake_request():
    """Minimal real Starlette Request; slowapi's @limiter.limit validates the type."""
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 0), "query_string": b""}
    return Request(scope)


def _retrieval(context: str):
    return {
        "context": context,
        "citations": [{"index": 0}] if context else [],
        "freshness_warning": False,
        "oldest_source_date": None,
        "newest_source_date": None,
    }


def _manager():
    m = MagicMock()
    m.create_session = AsyncMock(return_value="sess-1")
    m.get_session = AsyncMock(return_value={"session_id": "sess-1"})
    m.add_user_message = AsyncMock()
    m.get_conversation_history = AsyncMock(return_value=[])
    m.add_assistant_message = AsyncMock(return_value="msg-1")
    return m


def _stream_gen(tokens, *, raise_after=False):
    async def _gen(*args, **kwargs):
        _gen.kwargs = kwargs
        for t in tokens:
            yield t
        if raise_after:
            raise RuntimeError("mid-flight boom")

    return _gen


async def _drain(response):
    body = ""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, str) else chunk.decode()
    return body


class TestRagChatStreamTracing:
    async def test_stream_creates_trace_before_returning_response(self):
        p_trace = MagicMock(return_value=(MagicMock(), "t-1"))
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "create_rag_trace", p_trace),
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)

        # Trace created synchronously in the outer scope, before the body streams.
        p_trace.assert_called_once()
        assert response is not None

    async def test_stream_passes_trace_id_into_retrieve(self):
        pipeline = MagicMock()
        pipeline.retrieve = AsyncMock(return_value=_retrieval("ctx"))
        gen = _stream_gen(["a", "b"])
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "release"),
            patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline),
            patch.object(rag_conversation, "create_rag_trace", return_value=(MagicMock(), "t-1")),
            patch.object(rag_conversation, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(rag_conversation, "generate_answer_stream", gen),
            patch.object(rag_conversation, "schedule_rag_online_eval"),
            patch.object(rag_conversation, "flush_langfuse"),
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
            await _drain(response)

        assert pipeline.retrieve.call_args.kwargs["trace_id"] == "t-1"

    async def test_stream_attaches_callback_to_generate_answer_stream(self):
        pipeline = MagicMock()
        pipeline.retrieve = AsyncMock(return_value=_retrieval("ctx"))
        gen = _stream_gen(["a", "b"])
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "release"),
            patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline),
            patch.object(rag_conversation, "create_rag_trace", return_value=(MagicMock(), "t-1")),
            patch.object(rag_conversation, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(rag_conversation, "generate_answer_stream", gen),
            patch.object(rag_conversation, "schedule_rag_online_eval"),
            patch.object(rag_conversation, "flush_langfuse"),
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
            await _drain(response)

        assert gen.kwargs["callbacks"] == [_SENTINEL]

    async def test_stream_flushes_after_done(self):
        pipeline = MagicMock()
        pipeline.retrieve = AsyncMock(return_value=_retrieval("ctx"))
        calls: list[str] = []
        mock_trace = MagicMock()

        def _record_flush():
            calls.append("flush")

        gen = _stream_gen(["a"])
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "release"),
            patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline),
            patch.object(rag_conversation, "create_rag_trace", return_value=(mock_trace, "t-1")),
            patch.object(rag_conversation, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(rag_conversation, "generate_answer_stream", gen),
            patch.object(rag_conversation, "schedule_rag_online_eval"),
            patch.object(rag_conversation, "flush_langfuse", side_effect=_record_flush),
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
            body = await _drain(response)

        assert f"event: {RAGEventType.DONE}" in body
        assert calls == ["flush"]  # flushed exactly once
        # Trace update happened before flush (post-DONE, inside try).
        mock_trace.update.assert_called_once()

    async def test_stream_refusal_sets_refusal_true_and_skips_eval(self):
        pipeline = MagicMock()
        pipeline.retrieve = AsyncMock(return_value=_retrieval(""))
        mock_trace = MagicMock()
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "release"),
            patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline),
            patch.object(rag_conversation, "create_rag_trace", return_value=(mock_trace, "t-1")),
            patch.object(rag_conversation, "generate_answer_stream", _stream_gen([], raise_after=False)),
            patch.object(rag_conversation, "schedule_rag_online_eval") as p_eval,
            patch.object(rag_conversation, "flush_langfuse") as p_flush,
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
            await _drain(response)

        _, kwargs = mock_trace.update.call_args
        assert kwargs["metadata"][RAG_TRACE_META_REFUSAL] is True
        p_eval.assert_not_called()
        p_flush.assert_called_once()

    async def test_stream_error_midflight_still_flushes(self):
        pipeline = MagicMock()
        pipeline.retrieve = AsyncMock(return_value=_retrieval("ctx"))
        gen = _stream_gen(["a"], raise_after=True)
        with (
            patch.object(rag_conversation, "ConversationManager", return_value=_manager()),
            patch.object(rag_conversation, "try_acquire", AsyncMock(return_value=True)),
            patch.object(rag_conversation, "release"),
            patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline),
            patch.object(rag_conversation, "create_rag_trace", return_value=(MagicMock(), "t-1")),
            patch.object(rag_conversation, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(rag_conversation, "generate_answer_stream", gen),
            patch.object(rag_conversation, "schedule_rag_online_eval"),
            patch.object(rag_conversation, "flush_langfuse") as p_flush,
        ):
            response = await rag_conversation.rag_chat_stream(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
            body = await _drain(response)

        assert f"event: {RAGEventType.ERROR}" in body
        p_flush.assert_called_once()
