"""
Unit tests for RAG Quality Evaluator.

Tests the run_evaluation function: happy path, metric failures, fail-soft behavior.
All DeepEval and DB dependencies are mocked.
"""

import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_metric(name: str, score: float, passed: bool) -> MagicMock:
    """Create a mock DeepEval metric."""
    metric = MagicMock()
    metric.__class__ = type(name, (), {})
    metric.__class__.__name__ = name
    metric.score = score
    metric.is_successful.return_value = passed
    metric.measure = MagicMock()
    return metric


@pytest.fixture
def mock_eval_repo():
    """Mock EvaluationsRepository with all async methods."""
    repo = AsyncMock()
    repo.create_evaluation = AsyncMock(return_value="eval-123")
    repo.update_scores = AsyncMock(return_value=True)
    repo.mark_failed = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def eval_env(mock_eval_repo):
    """
    Set up mocked environment for evaluator tests.

    Patches DB, DeepEval imports, and returns (run_evaluation, eval_repo, create_metrics_mock).
    """
    mock_create_metrics = MagicMock()
    mock_llm_test_case = MagicMock()

    # Mock the deepeval modules in sys.modules so the lazy import inside run_evaluation works
    mock_deepeval = MagicMock()
    mock_test_case_module = MagicMock()
    mock_test_case_module.LLMTestCase = mock_llm_test_case

    with patch("rag.evaluation.evaluator.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("rag.evaluation.evaluator.EvaluationsRepository", return_value=mock_eval_repo):
        mock_get_db.return_value = MagicMock()

        # We need to pre-populate sys.modules so the `from deepeval.test_case import LLMTestCase`
        # and `from rag.evaluation.metrics import create_metrics` inside run_evaluation() work
        original_deepeval = sys.modules.get("deepeval")
        original_test_case = sys.modules.get("deepeval.test_case")

        sys.modules["deepeval"] = mock_deepeval
        sys.modules["deepeval.test_case"] = mock_test_case_module

        # Patch create_metrics at its source module
        with patch("rag.evaluation.metrics.create_metrics", mock_create_metrics):
            from rag.evaluation.evaluator import run_evaluation
            yield run_evaluation, mock_eval_repo, mock_create_metrics, mock_llm_test_case

        # Restore
        if original_deepeval is not None:
            sys.modules["deepeval"] = original_deepeval
        else:
            sys.modules.pop("deepeval", None)
        if original_test_case is not None:
            sys.modules["deepeval.test_case"] = original_test_case
        else:
            sys.modules.pop("deepeval.test_case", None)


class TestRunEvaluation:
    """Tests for rag.evaluation.evaluator.run_evaluation()."""

    async def test_happy_path_stores_scores(self, eval_env):
        run_evaluation, eval_repo, create_metrics, _ = eval_env
        metric1 = _make_metric("FaithfulnessMetric", 0.9, True)
        metric2 = _make_metric("AnswerRelevancyMetric", 0.85, True)
        create_metrics.return_value = [metric1, metric2]

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="What is RAG?",
            answer="RAG is retrieval augmented generation.",
            contexts=["Context about RAG."],
        )

        assert result is not None
        assert result["evaluation_id"] == "eval-123"
        assert result["overall_passed"] is True
        assert "FaithfulnessMetric" in result["scores"]
        assert result["scores"]["FaithfulnessMetric"] == 0.9
        assert result["scores"]["AnswerRelevancyMetric"] == 0.85
        eval_repo.update_scores.assert_awaited_once()

    async def test_creates_pending_record_first(self, eval_env):
        run_evaluation, eval_repo, create_metrics, _ = eval_env
        metric = _make_metric("FaithfulnessMetric", 0.9, True)
        create_metrics.return_value = [metric]

        call_order = []

        async def track_create(*args, **kwargs):
            call_order.append("create")
            return "eval-123"

        eval_repo.create_evaluation.side_effect = track_create

        def track_measure(test_case):
            call_order.append("measure")

        metric.measure = track_measure

        await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert call_order.index("create") < call_order.index("measure")

    async def test_metric_failure_logs_zero_score(self, eval_env):
        run_evaluation, eval_repo, create_metrics, _ = eval_env
        good_metric = _make_metric("FaithfulnessMetric", 0.9, True)
        bad_metric = _make_metric("HallucinationMetric", 0.0, False)
        bad_metric.measure = MagicMock(side_effect=RuntimeError("metric crashed"))
        create_metrics.return_value = [good_metric, bad_metric]

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert result is not None
        assert result["scores"]["FaithfulnessMetric"] == 0.9
        assert result["scores"]["HallucinationMetric"] == 0.0
        assert result["overall_passed"] is False

    async def test_all_metrics_pass_sets_overall_passed_true(self, eval_env):
        run_evaluation, _, create_metrics, _ = eval_env
        create_metrics.return_value = [
            _make_metric("FaithfulnessMetric", 0.9, True),
            _make_metric("AnswerRelevancyMetric", 0.85, True),
        ]

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert result["overall_passed"] is True

    async def test_one_metric_fails_threshold_sets_overall_passed_false(self, eval_env):
        run_evaluation, _, create_metrics, _ = eval_env
        create_metrics.return_value = [
            _make_metric("FaithfulnessMetric", 0.9, True),
            _make_metric("AnswerRelevancyMetric", 0.3, False),
        ]

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert result["overall_passed"] is False

    async def test_unexpected_exception_marks_failed(self, eval_env):
        run_evaluation, eval_repo, create_metrics, _ = eval_env
        create_metrics.side_effect = RuntimeError("unexpected")

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert result is None
        eval_repo.mark_failed.assert_awaited_once()

    async def test_returns_duration_ms(self, eval_env):
        run_evaluation, _, create_metrics, _ = eval_env
        create_metrics.return_value = [_make_metric("FaithfulnessMetric", 0.9, True)]

        result = await run_evaluation(
            evaluation_id="eval-123",
            session_id="sess-456",
            query="Q",
            answer="A",
            contexts=["C"],
        )

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0

    async def test_deepeval_import_error_marks_failed(self):
        """If deepeval is not installed, mark_failed should be called."""
        mock_eval_repo = AsyncMock()
        mock_eval_repo.create_evaluation = AsyncMock()
        mock_eval_repo.mark_failed = AsyncMock(return_value=True)

        # Remove deepeval from sys.modules to trigger ImportError on lazy import
        saved = {}
        for key in list(sys.modules.keys()):
            if "deepeval" in key:
                saved[key] = sys.modules.pop(key)
        saved_metrics = sys.modules.pop("rag.evaluation.metrics", None)

        try:
            # Patch at the source modules BEFORE reload so reload picks up the mocks
            mock_get_db = AsyncMock(return_value=MagicMock())
            with patch("db.connection.get_database", mock_get_db), \
                 patch("db.repositories.rag_evaluations.EvaluationsRepository", return_value=mock_eval_repo):

                import importlib
                import rag.evaluation.evaluator as eval_module
                importlib.reload(eval_module)

                result = await eval_module.run_evaluation(
                    evaluation_id="eval-123",
                    session_id="sess-456",
                    query="Q",
                    answer="A",
                    contexts=["C"],
                )

                assert result is None
                mock_eval_repo.mark_failed.assert_awaited_once()
        finally:
            sys.modules.update(saved)
            if saved_metrics is not None:
                sys.modules["rag.evaluation.metrics"] = saved_metrics
