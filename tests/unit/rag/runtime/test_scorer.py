"""
Unit tests for the runtime scorer.

The scorer is the orchestrator that:
  1. Writes a pending record to MongoDB (rag_evaluations)
  2. Runs the LLM judges (one per enabled metric)
  3. Dual-writes scores to MongoDB and to Langfuse via langfuse.score()

Mongo and Langfuse failures are independent and fail-soft.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import EvaluationMetric


def _make_judge_result(score: float | None, reasoning: str = "ok", error: str | None = None):
    from rag.evaluation.runtime.judge import JudgeResult

    return JudgeResult(score=score, reasoning=reasoning, error=error)


@pytest.fixture
def mock_eval_repo():
    repo = AsyncMock()
    repo.create_evaluation = AsyncMock(return_value="eval-1")
    repo.update_scores = AsyncMock(return_value=True)
    repo.mark_failed = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_langfuse_client():
    client = MagicMock()
    client.score = MagicMock()
    return client


@pytest.fixture
def runtime_eval_settings():
    """Mock RuntimeEvalSettings with the three default runtime metrics enabled."""
    s = MagicMock()
    s.metrics = ["faithfulness", "answer_relevancy", "hallucination"]
    s.faithfulness_threshold = 0.7
    s.answer_relevancy_threshold = 0.7
    s.hallucination_threshold = 0.5
    s.eval_model = "gpt-4.1-mini"
    s.judge_timeout_seconds = 30
    return s


@pytest.fixture
def patched_scorer_env(mock_eval_repo, mock_langfuse_client, runtime_eval_settings):
    """
    Patch the scorer module's collaborators:
      - get_database / EvaluationsRepository
      - get_langfuse_client
      - get_settings().runtime_eval
      - LLMJudge so we don't hit a real LLM
    """
    judge_instance = MagicMock()
    judge_instance.evaluate = AsyncMock(return_value=_make_judge_result(0.9))

    settings_obj = MagicMock()
    settings_obj.runtime_eval = runtime_eval_settings

    with (
        patch("rag.evaluation.runtime.scorer.get_database", new_callable=AsyncMock) as p_db,
        patch("rag.evaluation.runtime.scorer.EvaluationsRepository", return_value=mock_eval_repo),
        patch("rag.evaluation.runtime.scorer.get_langfuse_client", return_value=mock_langfuse_client),
        patch("rag.evaluation.runtime.scorer.get_settings", return_value=settings_obj),
        patch("rag.evaluation.runtime.scorer.LLMJudge", return_value=judge_instance),
    ):
        p_db.return_value = MagicMock()
        yield {
            "repo": mock_eval_repo,
            "langfuse": mock_langfuse_client,
            "judge": judge_instance,
            "settings": runtime_eval_settings,
        }


class TestScoreResponse:
    """Tests for rag.evaluation.runtime.scorer.score_response."""

    async def test_writes_pending_record_before_running_judges(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        call_order: list[str] = []

        async def track_create(*_a, **_kw):
            call_order.append("create")
            return "eval-1"

        async def track_evaluate(*_a, **_kw):
            call_order.append("evaluate")
            return _make_judge_result(0.9)

        env["repo"].create_evaluation.side_effect = track_create
        env["judge"].evaluate.side_effect = track_evaluate

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        assert call_order.index("create") < call_order.index("evaluate")

    async def test_writes_scores_to_mongo_keyed_by_enum_value(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["judge"].evaluate.side_effect = [
            _make_judge_result(0.9),  # faithfulness
            _make_judge_result(0.8),  # answer_relevancy
            _make_judge_result(0.2),  # hallucination
        ]

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        env["repo"].update_scores.assert_awaited_once()
        kwargs = env["repo"].update_scores.await_args.kwargs
        scores = kwargs["scores"]
        # Keys are StrEnum values, not DeepEval class names
        assert set(scores.keys()) == {
            str(EvaluationMetric.FAITHFULNESS),
            str(EvaluationMetric.ANSWER_RELEVANCY),
            str(EvaluationMetric.HALLUCINATION),
        }
        assert scores[str(EvaluationMetric.FAITHFULNESS)] == pytest.approx(0.9)

    async def test_posts_one_langfuse_score_per_metric_with_trace_id(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["judge"].evaluate.side_effect = [
            _make_judge_result(0.9, reasoning="solid"),
            _make_judge_result(0.8, reasoning="ok"),
            _make_judge_result(0.2, reasoning="low hallucination"),
        ]

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-42",
        )

        assert env["langfuse"].score.call_count == 3
        names_posted = {c.kwargs["name"] for c in env["langfuse"].score.call_args_list}
        assert names_posted == {
            str(EvaluationMetric.FAITHFULNESS),
            str(EvaluationMetric.ANSWER_RELEVANCY),
            str(EvaluationMetric.HALLUCINATION),
        }
        for c in env["langfuse"].score.call_args_list:
            assert c.kwargs["trace_id"] == "trace-42"

    async def test_skips_langfuse_when_trace_id_is_none(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id=None,
        )

        env["langfuse"].score.assert_not_called()
        env["repo"].update_scores.assert_awaited_once()

    async def test_skips_langfuse_when_client_is_none(self, patched_scorer_env):
        from rag.evaluation.runtime import scorer

        with patch.object(scorer, "get_langfuse_client", return_value=None):
            await scorer.score_response(
                evaluation_id="eval-1",
                session_id="sess-1",
                query="q",
                answer="a",
                contexts=["c"],
                langfuse_trace_id="trace-1",
            )

        patched_scorer_env["repo"].update_scores.assert_awaited_once()
        patched_scorer_env["langfuse"].score.assert_not_called()

    async def test_one_judge_failure_does_not_block_others(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["judge"].evaluate.side_effect = [
            _make_judge_result(0.9),
            RuntimeError("judge crashed"),
            _make_judge_result(0.2),
        ]

        result = await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        env["repo"].update_scores.assert_awaited_once()
        kwargs = env["repo"].update_scores.await_args.kwargs
        # The crashed metric is omitted (no score) but overall_passed must be False
        assert str(EvaluationMetric.ANSWER_RELEVANCY) not in kwargs["scores"]
        assert kwargs["overall_passed"] is False
        # Langfuse gets a score posted only for the metrics that produced one
        assert env["langfuse"].score.call_count == 2
        assert result is not None

    async def test_mongo_failure_does_not_prevent_langfuse_posting(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["repo"].update_scores.side_effect = RuntimeError("mongo down")

        result = await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        assert env["langfuse"].score.call_count == 3
        # Mongo failure is fail-soft; the function returns the result dict regardless.
        assert result is not None

    async def test_langfuse_failure_does_not_rollback_mongo(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["langfuse"].score.side_effect = RuntimeError("langfuse down")

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        env["repo"].update_scores.assert_awaited_once()

    async def test_overall_passed_honours_thresholds(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        # answer_relevancy below 0.7 threshold should flip overall_passed to False
        env["judge"].evaluate.side_effect = [
            _make_judge_result(0.9),  # faithfulness >= 0.7 OK
            _make_judge_result(0.3),  # answer_relevancy < 0.7 FAIL
            _make_judge_result(0.2),  # hallucination <= 0.5 OK (lower is better)
        ]

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        kwargs = env["repo"].update_scores.await_args.kwargs
        assert kwargs["overall_passed"] is False

    async def test_overall_passed_true_when_all_metrics_within_threshold(self, patched_scorer_env):
        from rag.evaluation.runtime.scorer import score_response

        env = patched_scorer_env
        env["judge"].evaluate.side_effect = [
            _make_judge_result(0.9),
            _make_judge_result(0.85),
            _make_judge_result(0.1),
        ]

        await score_response(
            evaluation_id="eval-1",
            session_id="sess-1",
            query="q",
            answer="a",
            contexts=["c"],
            langfuse_trace_id="trace-1",
        )

        kwargs = env["repo"].update_scores.await_args.kwargs
        assert kwargs["overall_passed"] is True
