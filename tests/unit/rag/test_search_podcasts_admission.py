"""COST-1/COST-2/COST-4b/OBS-1/OBS-2/F5 wiring on the public search path.

No Docker: pipeline + repos + admission are mocked. Asserts the guards run
BEFORE the embedding (retrieval) call, and that the key_id threads into the trace
and the podcast surface is unbounded-by-default.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from rag.mcp import tools as mcp_tools
from rag.quota.admission import ADMISSION_REASON_DAILY_QUOTA, QueryAdmissionError


def _stub_retrieval(captured: dict):
    async def _fake_retrieve(self, *args, **kwargs):
        captured.update(kwargs)
        captured["__retrieved__"] = True
        return {
            "context": "ctx",
            "citations": [{"index": 0}],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }

    return _fake_retrieve


@pytest.fixture
def _patched(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _stub_retrieval(captured))
    monkeypatch.setattr(mcp_tools, "flush_langfuse", lambda: None)
    # Resolve a concrete key_id from the auth context.
    monkeypatch.setattr(mcp_tools, "resolve_current_key_id", lambda: "key-abc")
    monkeypatch.setattr(mcp_tools, "_get_quota_repo", AsyncMock(return_value=MagicMock()))
    return captured


class TestSearchAdmission:
    async def test_admits_and_threads_key_id_into_trace(self, _patched, monkeypatch):
        p_trace = MagicMock(return_value=(MagicMock(), "t-1"))
        monkeypatch.setattr(mcp_tools, "create_rag_trace", p_trace)
        monkeypatch.setattr(mcp_tools, "enforce_query_admission", AsyncMock())
        monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", AsyncMock())
        await mcp_tools.search_podcasts(query="q")
        assert _patched["__retrieved__"] is True
        # OBS-1: the resolved key_id is passed as user_id on the trace.
        assert p_trace.call_args.kwargs["user_id"] == "key-abc"
        # F5: podcast surface is unbounded-by-default.
        assert _patched["unbounded_default_window"] is True

    async def test_over_quota_rejects_before_embedding(self, _patched, monkeypatch):
        monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, None))
        monkeypatch.setattr(
            mcp_tools, "enforce_query_admission",
            AsyncMock(side_effect=QueryAdmissionError("over", reason=ADMISSION_REASON_DAILY_QUOTA)),
        )
        monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", AsyncMock())
        p_reject = MagicMock()
        monkeypatch.setattr(mcp_tools, "emit_reject", p_reject)
        with pytest.raises(QueryAdmissionError):
            await mcp_tools.search_podcasts(query="q")
        # Retrieval (and its embedding) was NEVER reached.
        assert "__retrieved__" not in _patched
        # OBS-2: the reject was observed with the reason + key_id.
        p_reject.assert_called_once()
        assert p_reject.call_args.kwargs["reason"] == ADMISSION_REASON_DAILY_QUOTA
        assert p_reject.call_args.kwargs["key_id"] == "key-abc"

    async def test_validation_reject_is_observed(self, _patched, monkeypatch):
        from rag.mcp.validation import MCPToolInputError

        monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, None))
        monkeypatch.setattr(mcp_tools, "enforce_query_admission", AsyncMock())
        monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", AsyncMock())
        # Force a boundary-validation failure on the slug.
        monkeypatch.setattr(mcp_tools, "validate_podcast_slug", MagicMock(side_effect=MCPToolInputError("bad slug")))
        p_reject = MagicMock()
        monkeypatch.setattr(mcp_tools, "emit_reject", p_reject)
        with pytest.raises(MCPToolInputError):
            await mcp_tools.search_podcasts(query="q", podcast="BAD SLUG")
        assert "__retrieved__" not in _patched
        p_reject.assert_called_once()
        assert p_reject.call_args.kwargs["reason"] == mcp_tools.RAG_REJECT_REASON_VALIDATION

    async def test_global_breaker_trips_before_embedding(self, _patched, monkeypatch):
        monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, None))
        monkeypatch.setattr(mcp_tools, "enforce_query_admission", AsyncMock())
        monkeypatch.setattr(
            mcp_tools, "check_global_embed_breaker",
            AsyncMock(side_effect=QueryAdmissionError("breaker", reason="global_embed_breaker_open")),
        )
        monkeypatch.setattr(mcp_tools, "emit_reject", MagicMock())
        with pytest.raises(QueryAdmissionError):
            await mcp_tools.search_podcasts(query="q")
        assert "__retrieved__" not in _patched
