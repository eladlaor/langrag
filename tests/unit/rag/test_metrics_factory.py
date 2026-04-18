"""
Unit tests for DeepEval metrics factory.

Tests create_metrics(): metric creation, threshold propagation, unknown metrics, import errors.
"""

import logging
import sys

import pytest
from unittest.mock import MagicMock, patch


def _make_mock_settings(
    metrics: list[str] | None = None,
    faithfulness_threshold: float = 0.7,
    answer_relevancy_threshold: float = 0.7,
    contextual_relevancy_threshold: float = 0.5,
    hallucination_threshold: float = 0.5,
    eval_model: str = "gpt-4.1-mini",
) -> MagicMock:
    """Create a mock settings object matching DeepEvalSettings."""
    if metrics is None:
        metrics = ["faithfulness", "answer_relevancy", "hallucination"]
    settings = MagicMock()
    settings.deepeval.metrics = metrics
    settings.deepeval.faithfulness_threshold = faithfulness_threshold
    settings.deepeval.answer_relevancy_threshold = answer_relevancy_threshold
    settings.deepeval.contextual_relevancy_threshold = contextual_relevancy_threshold
    settings.deepeval.hallucination_threshold = hallucination_threshold
    settings.deepeval.eval_model = eval_model
    return settings


@pytest.fixture
def metric_mocks():
    """
    Mock DeepEval metric classes via sys.modules and return them.
    Patches get_settings on the metrics module for each test.
    """
    mock_faithfulness_cls = MagicMock()
    mock_answer_relevancy_cls = MagicMock()
    mock_hallucination_cls = MagicMock()
    mock_contextual_relevancy_cls = MagicMock()

    mock_metrics_module = MagicMock()
    mock_metrics_module.FaithfulnessMetric = mock_faithfulness_cls
    mock_metrics_module.AnswerRelevancyMetric = mock_answer_relevancy_cls
    mock_metrics_module.HallucinationMetric = mock_hallucination_cls
    mock_metrics_module.ContextualRelevancyMetric = mock_contextual_relevancy_cls

    saved_deepeval = sys.modules.get("deepeval")
    saved_deepeval_metrics = sys.modules.get("deepeval.metrics")

    sys.modules["deepeval"] = MagicMock()
    sys.modules["deepeval.metrics"] = mock_metrics_module

    yield {
        "FaithfulnessMetric": mock_faithfulness_cls,
        "AnswerRelevancyMetric": mock_answer_relevancy_cls,
        "HallucinationMetric": mock_hallucination_cls,
        "ContextualRelevancyMetric": mock_contextual_relevancy_cls,
    }

    if saved_deepeval is not None:
        sys.modules["deepeval"] = saved_deepeval
    else:
        sys.modules.pop("deepeval", None)
    if saved_deepeval_metrics is not None:
        sys.modules["deepeval.metrics"] = saved_deepeval_metrics
    else:
        sys.modules.pop("deepeval.metrics", None)


class TestCreateMetrics:
    """Tests for rag.evaluation.metrics.create_metrics()."""

    def test_creates_default_metrics(self, metric_mocks):
        settings = _make_mock_settings()

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            metrics = create_metrics()

        assert len(metrics) == 3

    def test_creates_single_metric(self, metric_mocks):
        settings = _make_mock_settings(metrics=["faithfulness"])

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            metrics = create_metrics()

        assert len(metrics) == 1
        metric_mocks["FaithfulnessMetric"].assert_called_once_with(
            threshold=0.7,
            model="gpt-4.1-mini",
        )

    def test_respects_custom_thresholds(self, metric_mocks):
        settings = _make_mock_settings(
            metrics=["faithfulness"],
            faithfulness_threshold=0.9,
            eval_model="gpt-4o",
        )

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            create_metrics()

        metric_mocks["FaithfulnessMetric"].assert_called_with(
            threshold=0.9,
            model="gpt-4o",
        )

    def test_includes_contextual_relevancy_when_configured(self, metric_mocks):
        settings = _make_mock_settings(metrics=["contextual_relevancy"])

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            metrics = create_metrics()

        assert len(metrics) == 1
        metric_mocks["ContextualRelevancyMetric"].assert_called_once()

    def test_unknown_metric_logged_and_skipped(self, metric_mocks, caplog):
        settings = _make_mock_settings(metrics=["faithfulness", "nonexistent_metric"])

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            with caplog.at_level(logging.WARNING):
                metrics = create_metrics()

        assert len(metrics) == 1
        assert "nonexistent_metric" in caplog.text

    def test_empty_metrics_list_returns_empty(self, metric_mocks):
        settings = _make_mock_settings(metrics=[])

        with patch("rag.evaluation.metrics.get_settings", return_value=settings):
            from rag.evaluation.metrics import create_metrics
            metrics = create_metrics()

        assert metrics == []

    def test_import_error_when_deepeval_missing(self):
        """If deepeval is not installed, ImportError should be raised."""
        settings = _make_mock_settings()

        saved = {}
        for key in list(sys.modules.keys()):
            if "deepeval" in key:
                saved[key] = sys.modules.pop(key)

        try:
            with patch("rag.evaluation.metrics.get_settings", return_value=settings):
                import importlib
                import rag.evaluation.metrics as metrics_module
                importlib.reload(metrics_module)

                with pytest.raises(ImportError, match="deepeval"):
                    metrics_module.create_metrics()
        finally:
            sys.modules.update(saved)
