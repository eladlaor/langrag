"""Unit tests: the non-streaming rag_chat handler creates one Langfuse trace,
threads trace_id into retrieval, attaches a callback to generation, flags refusal
on empty context, flushes on every exit path, and schedules online eval only on
a real answer. Deps are mocked so the test runs without Docker/network."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api import rag_conversation
from constants import RAG_TRACE_META_REFUSAL
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


@asynccontextmanager
async def _noop_slot():
    yield


def _patch_common(context: str, gen: AsyncMock, stack):
    """Patch shared rag_chat dependencies. Returns (mock_trace,)."""
    mock_trace = MagicMock()
    manager = MagicMock()
    manager.create_session = AsyncMock(return_value="sess-1")
    manager.get_session = AsyncMock(return_value={"session_id": "sess-1"})
    manager.add_user_message = AsyncMock()
    manager.get_conversation_history = AsyncMock(return_value=[])
    manager.add_assistant_message = AsyncMock(return_value="msg-1")

    pipeline = MagicMock()
    pipeline.retrieve = AsyncMock(return_value=_retrieval(context))

    stack.enter_context(patch.object(rag_conversation, "ConversationManager", return_value=manager))
    stack.enter_context(patch.object(rag_conversation, "RetrievalPipeline", return_value=pipeline))
    stack.enter_context(patch.object(rag_conversation, "rag_slot", _noop_slot))
    stack.enter_context(patch.object(rag_conversation, "create_rag_trace", return_value=(mock_trace, "t-1")))
    stack.enter_context(patch.object(rag_conversation, "get_langfuse_callback_handler", return_value=_SENTINEL))
    stack.enter_context(patch.object(rag_conversation, "generate_answer", gen))
    return mock_trace, pipeline


class TestRagChatTracing:
    async def test_rag_chat_passes_trace_id_into_retrieve(self):
        import contextlib

        gen = AsyncMock(return_value="the answer")
        with contextlib.ExitStack() as stack:
            _, pipeline = _patch_common("some context", gen, stack)
            stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)

        assert pipeline.retrieve.call_args.kwargs["trace_id"] == "t-1"

    async def test_rag_chat_attaches_callback_to_generate_answer(self):
        import contextlib

        gen = AsyncMock(return_value="the answer")
        with contextlib.ExitStack() as stack:
            _patch_common("some context", gen, stack)
            stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)

        assert gen.call_args.kwargs["callbacks"] == [_SENTINEL]

    async def test_rag_chat_refusal_sets_refusal_metadata_true(self):
        import contextlib

        gen = AsyncMock(side_effect=AssertionError("generation must not run on empty context"))
        with contextlib.ExitStack() as stack:
            mock_trace, _ = _patch_common("", gen, stack)
            p_eval = stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)

        _, kwargs = mock_trace.update.call_args
        assert kwargs["metadata"][RAG_TRACE_META_REFUSAL] is True
        gen.assert_not_called()
        p_eval.assert_not_called()

    async def test_rag_chat_flushes_langfuse_on_success_and_error(self):
        import contextlib

        # Success path.
        gen_ok = AsyncMock(return_value="the answer")
        with contextlib.ExitStack() as stack:
            _patch_common("some context", gen_ok, stack)
            stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            p_flush = stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
        p_flush.assert_called_once()

        # Error path: generation raises -> 500, but finally still flushes.
        gen_err = AsyncMock(side_effect=RuntimeError("boom"))
        with contextlib.ExitStack() as stack:
            _patch_common("some context", gen_err, stack)
            stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            p_flush = stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            with pytest.raises(rag_conversation.HTTPException):
                await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)
        p_flush.assert_called_once()

    async def test_rag_chat_schedules_online_eval_on_answer(self):
        import contextlib

        gen = AsyncMock(return_value="the answer")
        with contextlib.ExitStack() as stack:
            _patch_common("some context", gen, stack)
            p_eval = stack.enter_context(patch.object(rag_conversation, "schedule_rag_online_eval"))
            stack.enter_context(patch.object(rag_conversation, "flush_langfuse"))
            await rag_conversation.rag_chat(request=_fake_request(), body=RAGChatRequest(query="q"), key_record=_KEY_RECORD)

        p_eval.assert_called_once()
        assert p_eval.call_args.kwargs["answer"] == "the answer"
        assert p_eval.call_args.kwargs["trace_id"] == "t-1"
