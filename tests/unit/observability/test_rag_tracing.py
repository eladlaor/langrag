"""Unit tests for the live-RAG tracing + online-eval helper.

Covers: guarded trace creation (kill switch, field shape, query truncation) and
the fire-and-forget online-eval scheduler gating + fail-soft behavior. Also an
AST guard proving the module never imports the orphaned rag_conversation graph."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from constants import (
    RAG_TRACE_INPUT_MAX,
    RAG_TRACE_META_CONTENT_SOURCES,
    RAG_TRACE_META_DATE_END,
    RAG_TRACE_META_DATE_START,
    RAGTraceName,
)
from observability.llm import rag_tracing


def _make_settings(*, online: bool = True, runtime_enabled: bool = True, sampling: float = 1.0) -> MagicMock:
    s = MagicMock()
    s.rag.online_eval_enabled = online
    s.runtime_eval.enabled = runtime_enabled
    s.runtime_eval.sampling_rate = sampling
    return s


class TestCreateRagTrace:
    def test_create_rag_trace_returns_none_when_langfuse_disabled(self):
        with patch.object(rag_tracing, "is_langfuse_enabled", return_value=False):
            trace, trace_id = rag_tracing.create_rag_trace(
                name=RAGTraceName.REST_CHAT,
                user_id="u",
                session_id="s",
                query="q",
                content_sources=None,
                date_start=None,
                date_end=None,
                tags=["rag"],
            )
        assert trace is None
        assert trace_id is None

    def test_create_rag_trace_builds_trace_with_expected_fields(self):
        from datetime import UTC, datetime

        mock_trace = MagicMock()
        mock_trace.id = "t-1"
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace

        ds = datetime(2025, 1, 1, tzinfo=UTC)
        de = datetime(2025, 2, 1, tzinfo=UTC)

        with (
            patch.object(rag_tracing, "is_langfuse_enabled", return_value=True),
            patch.object(rag_tracing, "get_langfuse_client", return_value=mock_client),
        ):
            trace, trace_id = rag_tracing.create_rag_trace(
                name=RAGTraceName.REST_CHAT,
                user_id="owner-1",
                session_id="sess-1",
                query="hello",
                content_sources=["newsletter"],
                date_start=ds,
                date_end=de,
                tags=["rag", "sync"],
            )

        assert (trace, trace_id) == (mock_trace, "t-1")
        _, kwargs = mock_client.trace.call_args
        assert kwargs["name"] == str(RAGTraceName.REST_CHAT)
        assert kwargs["user_id"] == "owner-1"
        assert kwargs["session_id"] == "sess-1"
        assert kwargs["tags"] == ["rag", "sync"]
        meta = kwargs["metadata"]
        assert meta[RAG_TRACE_META_CONTENT_SOURCES] == ["newsletter"]
        assert meta[RAG_TRACE_META_DATE_START] == "2025-01-01"
        assert meta[RAG_TRACE_META_DATE_END] == "2025-02-01"

    def test_create_rag_trace_truncates_long_query(self):
        mock_trace = MagicMock()
        mock_trace.id = "t-1"
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace
        long_query = "x" * (RAG_TRACE_INPUT_MAX + 500)

        with (
            patch.object(rag_tracing, "is_langfuse_enabled", return_value=True),
            patch.object(rag_tracing, "get_langfuse_client", return_value=mock_client),
        ):
            rag_tracing.create_rag_trace(
                name=RAGTraceName.REST_CHAT,
                user_id="u",
                session_id="s",
                query=long_query,
                content_sources=None,
                date_start=None,
                date_end=None,
                tags=["rag"],
            )

        _, kwargs = mock_client.trace.call_args
        assert len(kwargs["input"]) == RAG_TRACE_INPUT_MAX


class TestScheduleOnlineEval:
    def test_schedule_online_eval_disabled_when_master_flag_off(self):
        with (
            patch.object(rag_tracing, "get_settings", return_value=_make_settings(online=False)),
            patch.object(rag_tracing, "score_response", new_callable=AsyncMock) as p_score,
        ):
            result = rag_tracing.schedule_rag_online_eval(session_id="s", query="q", answer="a", contexts=["c"], trace_id="t-1")
        assert result is None
        p_score.assert_not_called()

    def test_schedule_online_eval_respects_runtime_eval_disabled(self):
        with (
            patch.object(rag_tracing, "get_settings", return_value=_make_settings(online=True, runtime_enabled=False)),
            patch.object(rag_tracing, "score_response", new_callable=AsyncMock) as p_score,
        ):
            result = rag_tracing.schedule_rag_online_eval(session_id="s", query="q", answer="a", contexts=["c"], trace_id="t-1")
        assert result is None
        p_score.assert_not_called()

    def test_schedule_online_eval_sampling_zero_no_task(self):
        with (
            patch.object(rag_tracing, "get_settings", return_value=_make_settings(sampling=0.0)),
            patch.object(rag_tracing, "score_response", new_callable=AsyncMock) as p_score,
        ):
            result = rag_tracing.schedule_rag_online_eval(session_id="s", query="q", answer="a", contexts=["c"], trace_id="t-1")
        assert result is None
        p_score.assert_not_called()

    async def test_schedule_online_eval_schedules_score_and_shadow(self):
        done = asyncio.Event()

        p_score = AsyncMock()
        p_shadow = AsyncMock(side_effect=lambda **_kw: done.set())

        with (
            patch.object(rag_tracing, "get_settings", return_value=_make_settings(sampling=1.0)),
            patch.object(rag_tracing, "score_response", p_score),
            patch.object(rag_tracing, "shadow_score_se", p_shadow),
        ):
            evaluation_id = rag_tracing.schedule_rag_online_eval(session_id="s", query="q", answer="a", contexts=["c"], trace_id="t-1")
            await asyncio.wait_for(done.wait(), timeout=1.0)

        assert isinstance(evaluation_id, str)
        p_score.assert_awaited_once()
        p_shadow.assert_awaited_once()
        assert p_score.await_args.kwargs["langfuse_trace_id"] == "t-1"
        assert p_shadow.await_args.kwargs["langfuse_trace_id"] == "t-1"

    async def test_schedule_online_eval_scorer_crash_is_swallowed(self):
        done = asyncio.Event()

        p_score = AsyncMock(side_effect=RuntimeError("judge boom"))
        p_shadow = AsyncMock(side_effect=lambda **_kw: done.set())

        with (
            patch.object(rag_tracing, "get_settings", return_value=_make_settings(sampling=1.0)),
            patch.object(rag_tracing, "score_response", p_score),
            patch.object(rag_tracing, "shadow_score_se", p_shadow),
        ):
            rag_tracing.schedule_rag_online_eval(session_id="s", query="q", answer="a", contexts=["c"], trace_id="t-1")
            # No exception must propagate; shadow still runs despite scorer crash.
            await asyncio.wait_for(done.wait(), timeout=1.0)

        p_score.assert_awaited_once()
        p_shadow.assert_awaited_once()


class TestNoOrphanImport:
    def test_rag_tracing_does_not_import_orphaned_graph(self):
        import ast
        import pathlib

        here = pathlib.Path(__file__).resolve()
        repo_root = here.parents[3]
        target = repo_root / "src" / "observability" / "llm" / "rag_tracing.py"
        assert target.exists(), f"rag_tracing module missing at {target}"

        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("graphs.rag_conversation"):
                    offenders.append(f"from {mod} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("graphs.rag_conversation"):
                        offenders.append(f"import {alias.name}")

        assert not offenders, f"rag_tracing.py must not import the orphaned graph: {offenders}"
