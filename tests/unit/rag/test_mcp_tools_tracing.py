"""Unit tests: the MCP rag_query / rag_search tools each create one Langfuse
trace, thread trace_id into retrieval, and (rag_query only) attach a callback to
generation + schedule online eval on a real answer / flag refusal on empty
context. rag_search never generates. All flush in finally. Deps mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

from constants import RAG_TRACE_META_REFUSAL
from rag.mcp import tools as mcp_tools

_SENTINEL = object()


def _retrieval(context: str, citations=None):
    return {
        "context": context,
        "citations": citations if citations is not None else ([{"index": 0}] if context else []),
        "freshness_warning": False,
        "oldest_source_date": None,
        "newest_source_date": None,
    }


def _patch_pipeline(monkeypatch, retrieval):
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    captured = {}

    async def _fake_retrieve(self, *args, **kwargs):
        captured.update(kwargs)
        return retrieval

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)
    return captured


class TestRagQueryTracing:
    async def test_rag_query_passes_trace_id_into_retrieve(self, monkeypatch):
        captured = _patch_pipeline(monkeypatch, _retrieval("ctx"))
        with (
            patch.object(mcp_tools, "create_rag_trace", return_value=(MagicMock(), "t-1")),
            patch.object(mcp_tools, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(mcp_tools, "generate_answer", AsyncMock(return_value="ans")),
            patch.object(mcp_tools, "schedule_rag_online_eval"),
            patch.object(mcp_tools, "flush_langfuse"),
        ):
            await mcp_tools.rag_query(query="q", session_id="s", user_id="mcp")
        assert captured["trace_id"] == "t-1"

    async def test_rag_query_attaches_callback_and_schedules_eval_on_answer(self, monkeypatch):
        _patch_pipeline(monkeypatch, _retrieval("ctx"))
        gen = AsyncMock(return_value="ans")
        with (
            patch.object(mcp_tools, "create_rag_trace", return_value=(MagicMock(), "t-1")),
            patch.object(mcp_tools, "get_langfuse_callback_handler", return_value=_SENTINEL),
            patch.object(mcp_tools, "generate_answer", gen),
            patch.object(mcp_tools, "schedule_rag_online_eval") as p_eval,
            patch.object(mcp_tools, "flush_langfuse"),
        ):
            await mcp_tools.rag_query(query="q", session_id="s", user_id="mcp")

        assert gen.call_args.kwargs["callbacks"] == [_SENTINEL]
        p_eval.assert_called_once()
        assert p_eval.call_args.kwargs["trace_id"] == "t-1"

    async def test_rag_query_refusal_sets_refusal_true_no_eval(self, monkeypatch):
        _patch_pipeline(monkeypatch, _retrieval(""))
        mock_trace = MagicMock()
        with (
            patch.object(mcp_tools, "create_rag_trace", return_value=(mock_trace, "t-1")),
            patch.object(mcp_tools, "generate_answer", AsyncMock(side_effect=AssertionError("no gen on empty"))),
            patch.object(mcp_tools, "schedule_rag_online_eval") as p_eval,
            patch.object(mcp_tools, "flush_langfuse"),
        ):
            await mcp_tools.rag_query(query="q", session_id="s", user_id="mcp")

        _, kwargs = mock_trace.update.call_args
        assert kwargs["metadata"][RAG_TRACE_META_REFUSAL] is True
        p_eval.assert_not_called()


class TestRagSearchTracing:
    async def test_rag_search_creates_trace_and_flushes_no_generation(self, monkeypatch):
        captured = _patch_pipeline(monkeypatch, _retrieval("ctx"))
        p_trace = MagicMock(return_value=(MagicMock(), "t-1"))
        with (
            patch.object(mcp_tools, "create_rag_trace", p_trace),
            patch.object(mcp_tools, "generate_answer", AsyncMock(side_effect=AssertionError("rag_search must not generate"))),
            patch.object(mcp_tools, "flush_langfuse") as p_flush,
        ):
            await mcp_tools.rag_search(query="q", session_id="s", user_id="mcp")

        p_trace.assert_called_once()
        assert captured["trace_id"] == "t-1"
        p_flush.assert_called_once()
