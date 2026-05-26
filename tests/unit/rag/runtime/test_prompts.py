"""
Unit tests for runtime evaluation prompt templates.

Verifies that a prompt exists for each runtime EvaluationMetric and that each
template carries the placeholders the judge will fill at call time.
"""

import pytest

from constants import EvaluationMetric


RUNTIME_METRICS = (
    EvaluationMetric.FAITHFULNESS,
    EvaluationMetric.ANSWER_RELEVANCY,
    EvaluationMetric.HALLUCINATION,
)


class TestPromptByMetric:
    """Tests for PROMPT_BY_METRIC mapping in rag.evaluation.runtime.prompts."""

    def test_module_exposes_prompt_by_metric(self):
        from rag.evaluation.runtime import prompts

        assert hasattr(prompts, "PROMPT_BY_METRIC")
        assert isinstance(prompts.PROMPT_BY_METRIC, dict)

    @pytest.mark.parametrize("metric", RUNTIME_METRICS)
    def test_each_runtime_metric_has_a_prompt(self, metric: EvaluationMetric):
        from rag.evaluation.runtime.prompts import PROMPT_BY_METRIC

        assert metric in PROMPT_BY_METRIC, f"Missing prompt for {metric}"
        template = PROMPT_BY_METRIC[metric]
        assert isinstance(template, str)
        assert template.strip(), f"Empty prompt for {metric}"

    @pytest.mark.parametrize("metric", RUNTIME_METRICS)
    def test_prompt_template_contains_required_placeholders(self, metric: EvaluationMetric):
        from rag.evaluation.runtime.prompts import PROMPT_BY_METRIC

        template = PROMPT_BY_METRIC[metric]
        for placeholder in ("{query}", "{answer}", "{context}"):
            assert placeholder in template, (
                f"Prompt for {metric} is missing placeholder {placeholder}"
            )

    @pytest.mark.parametrize("metric", RUNTIME_METRICS)
    def test_prompt_instructs_json_score_output(self, metric: EvaluationMetric):
        from rag.evaluation.runtime.prompts import PROMPT_BY_METRIC

        template = PROMPT_BY_METRIC[metric].lower()
        assert "json" in template, f"Prompt for {metric} must request JSON output"
        assert "score" in template, f"Prompt for {metric} must mention 'score'"
