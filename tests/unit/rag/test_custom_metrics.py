"""Unit tests for the date-aware custom RAG eval metrics."""

from types import SimpleNamespace

import pytest

from rag.evaluation.custom_metrics import (
    DateCitationComplianceMetric,
    DateFilterHonoredMetric,
    RefusalComplianceMetric,
)


def _make_case(*, actual_output: str = "", **metadata):
    return SimpleNamespace(actual_output=actual_output, additional_metadata=metadata)


class TestDateCitationCompliance:
    def test_full_compliance(self):
        metric = DateCitationComplianceMetric()
        answer = "MCP rolled out [1] [date: 2026-03-04]. Adoption surged [2] [date: 2026-03-15]."
        score = metric.measure(_make_case(actual_output=answer))
        assert score == 1.0
        assert metric.success is True

    def test_partial_compliance_fails(self):
        metric = DateCitationComplianceMetric()
        answer = "MCP rolled out [1] [date: 2026-03-04]. Adoption surged [2]."
        score = metric.measure(_make_case(actual_output=answer))
        assert 0.0 < score < 1.0
        assert metric.success is False

    def test_no_factual_sentences_passes_vacuously(self):
        metric = DateCitationComplianceMetric()
        score = metric.measure(_make_case(actual_output="I don't know."))
        assert score == 1.0

    def test_handles_dates_range_tag(self):
        metric = DateCitationComplianceMetric()
        answer = "Per [1] [dates: 2026-03-01 to 2026-03-31] the consensus held."
        assert metric.measure(_make_case(actual_output=answer)) == 1.0


class TestDateFilterHonored:
    def test_no_filter_is_vacuous_pass(self):
        metric = DateFilterHonoredMetric()
        score = metric.measure(_make_case(citations=[{"source_date_start": "2026-03-01", "source_date_end": "2026-03-15"}]))
        assert score == 1.0

    def test_all_in_window(self):
        metric = DateFilterHonoredMetric()
        case = _make_case(
            date_filter={"date_start": "2026-03-01", "date_end": "2026-03-31"},
            citations=[
                {"source_date_start": "2026-03-04", "source_date_end": "2026-03-04"},
                {"source_date_start": "2026-03-15", "source_date_end": "2026-03-21"},
            ],
        )
        assert metric.measure(case) == 1.0
        assert metric.success is True

    def test_one_out_of_window_fails(self):
        metric = DateFilterHonoredMetric()
        case = _make_case(
            date_filter={"date_start": "2026-03-01", "date_end": "2026-03-31"},
            citations=[
                {"source_date_start": "2026-03-04", "source_date_end": "2026-03-04"},
                {"source_date_start": "2026-04-15", "source_date_end": "2026-04-21"},
            ],
        )
        score = metric.measure(case)
        assert score == 0.5
        assert metric.success is False


class TestRefusalCompliance:
    def test_must_refuse_and_did_refuse(self):
        metric = RefusalComplianceMetric()
        case = _make_case(
            actual_output="No content was found within the requested date range.",
            must_refuse=True,
        )
        assert metric.measure(case) == 1.0

    def test_must_refuse_but_answered(self):
        metric = RefusalComplianceMetric()
        case = _make_case(
            actual_output="Sure, here is what happened in 2030 ...",
            must_refuse=True,
        )
        assert metric.measure(case) == 0.0

    def test_no_refusal_required(self):
        metric = RefusalComplianceMetric()
        case = _make_case(
            actual_output="MCP usage grew steadily.",
            must_refuse=False,
        )
        assert metric.measure(case) == 1.0
