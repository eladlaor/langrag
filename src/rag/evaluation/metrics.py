"""
DeepEval Metric Configuration

Factory for creating configured DeepEval metric instances.
"""

import logging

from config import get_settings
from constants import EvaluationMetric

logger = logging.getLogger(__name__)


def create_metrics() -> list:
    """
    Create configured DeepEval metric instances based on settings.

    Returns:
        List of DeepEval metric instances

    Raises:
        ImportError: If deepeval is not installed
    """
    try:
        from deepeval.metrics import (
            FaithfulnessMetric,
            AnswerRelevancyMetric,
            HallucinationMetric,
            ContextualRelevancyMetric,
        )
    except ImportError as e:
        raise ImportError(
            "deepeval is required for evaluation. "
            "Install with: uv add 'deepeval>=1.0.0'"
        ) from e

    settings = get_settings().deepeval
    metrics = []

    metric_map = {
        str(EvaluationMetric.FAITHFULNESS): lambda: FaithfulnessMetric(
            threshold=settings.faithfulness_threshold,
            model=settings.eval_model,
        ),
        str(EvaluationMetric.ANSWER_RELEVANCY): lambda: AnswerRelevancyMetric(
            threshold=settings.answer_relevancy_threshold,
            model=settings.eval_model,
        ),
        str(EvaluationMetric.CONTEXTUAL_RELEVANCY): lambda: ContextualRelevancyMetric(
            threshold=settings.contextual_relevancy_threshold,
            model=settings.eval_model,
        ),
        str(EvaluationMetric.HALLUCINATION): lambda: HallucinationMetric(
            threshold=settings.hallucination_threshold,
            model=settings.eval_model,
        ),
    }

    for metric_name in settings.metrics:
        factory = metric_map.get(metric_name)
        if factory:
            metrics.append(factory())
        else:
            logger.warning(f"Unknown evaluation metric: {metric_name}")

    return metrics
