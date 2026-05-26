"""
Unit tests for the rewired evaluate_node in the RAG conversation graph.

The node reads runtime_eval settings (NOT deepeval), schedules score_response
as a background task, and forwards the langfuse_trace_id from state. Failure
inside score_response must NOT propagate out of the node.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphs.state_keys import RAGConversationStateKeys as Keys


def _make_settings(enabled: bool = True, sampling_rate: float = 1.0) -> MagicMock:
    s = MagicMock()
    s.runtime_eval.enabled = enabled
    s.runtime_eval.sampling_rate = sampling_rate
    return s


def _base_state(trace_id: str | None = "trace-xyz") -> dict:
    state: dict = {
        Keys.SESSION_ID: "sess-1",
        Keys.QUERY: "q",
        Keys.ANSWER: "a",
        Keys.RERANKED_CHUNKS: [{"content": "c1"}, {"content": "c2"}],
    }
    if trace_id is not None:
        state[Keys.LANGFUSE_TRACE_ID] = trace_id
    return state


class TestEvaluateNodeWiring:
    async def test_disabled_returns_none_evaluation_id_and_schedules_no_task(self):
        from graphs.rag_conversation import nodes

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=False)),
            patch.object(nodes, "score_response", new_callable=AsyncMock) as p_score,
        ):
            result = await nodes.evaluate_node(_base_state())

        assert result == {Keys.EVALUATION_ID: None}
        p_score.assert_not_called()

    async def test_sampling_rate_zero_schedules_no_task(self):
        from graphs.rag_conversation import nodes

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=True, sampling_rate=0.0)),
            patch.object(nodes, "score_response", new_callable=AsyncMock) as p_score,
        ):
            result = await nodes.evaluate_node(_base_state())

        assert result == {Keys.EVALUATION_ID: None}
        p_score.assert_not_called()

    async def test_sampling_rate_one_schedules_one_background_task(self):
        from graphs.rag_conversation import nodes

        scheduled = asyncio.Event()

        async def fake_score(**_kwargs):
            scheduled.set()

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=True, sampling_rate=1.0)),
            patch.object(nodes, "score_response", side_effect=fake_score) as p_score,
        ):
            result = await nodes.evaluate_node(_base_state())
            # Let the scheduled background task run
            await asyncio.wait_for(scheduled.wait(), timeout=1.0)

        assert result[Keys.EVALUATION_ID] is not None
        assert isinstance(result[Keys.EVALUATION_ID], str)
        p_score.assert_called_once()

    async def test_forwards_langfuse_trace_id_from_state(self):
        from graphs.rag_conversation import nodes

        captured: dict = {}

        async def fake_score(**kwargs):
            captured.update(kwargs)

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=True, sampling_rate=1.0)),
            patch.object(nodes, "score_response", side_effect=fake_score),
        ):
            await nodes.evaluate_node(_base_state(trace_id="trace-abc"))
            # Background task must complete
            for _ in range(50):
                if "langfuse_trace_id" in captured:
                    break
                await asyncio.sleep(0.01)

        assert captured.get("langfuse_trace_id") == "trace-abc"

    async def test_missing_trace_id_in_state_forwards_none(self):
        from graphs.rag_conversation import nodes

        captured: dict = {}

        async def fake_score(**kwargs):
            captured.update(kwargs)

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=True, sampling_rate=1.0)),
            patch.object(nodes, "score_response", side_effect=fake_score),
        ):
            await nodes.evaluate_node(_base_state(trace_id=None))
            for _ in range(50):
                if "langfuse_trace_id" in captured:
                    break
                await asyncio.sleep(0.01)

        # The kwarg must be passed (None is fine), not silently omitted
        assert "langfuse_trace_id" in captured
        assert captured["langfuse_trace_id"] is None

    async def test_score_response_raising_does_not_propagate(self):
        from graphs.rag_conversation import nodes

        async def boom(**_kwargs):
            raise RuntimeError("score_response crashed")

        with (
            patch.object(nodes, "get_settings", return_value=_make_settings(enabled=True, sampling_rate=1.0)),
            patch.object(nodes, "score_response", side_effect=boom),
        ):
            # The node returns synchronously; the background task swallows the error
            result = await nodes.evaluate_node(_base_state())
            # Let the background task run and fail
            await asyncio.sleep(0.05)

        assert result[Keys.EVALUATION_ID] is not None

    def test_node_module_does_not_import_legacy_evaluator(self):
        """
        Static AST check: graphs/rag_conversation/nodes.py must NOT import the
        legacy CI-orphaned `rag.evaluation.evaluator` module. The runtime scorer
        lives at `rag.evaluation.runtime.scorer` instead.

        Done as an AST check (not a sys.modules sweep) so this test never pollutes
        the import cache for other tests in the same session.
        """
        import ast
        import pathlib

        here = pathlib.Path(__file__).resolve()
        repo_root = here.parents[4]
        target = repo_root / "src" / "graphs" / "rag_conversation" / "nodes.py"
        assert target.exists(), f"Node module missing at {target}"

        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "rag.evaluation.evaluator" or mod.startswith("deepeval"):
                    offenders.append(f"from {mod} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "rag.evaluation.evaluator" or alias.name.startswith("deepeval"):
                        offenders.append(f"import {alias.name}")

        assert not offenders, (
            f"graphs/rag_conversation/nodes.py must not import the legacy "
            f"evaluator or deepeval: {offenders}"
        )
