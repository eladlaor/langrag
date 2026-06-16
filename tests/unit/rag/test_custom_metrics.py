"""Unit tests for the date-aware custom RAG eval metrics."""

from types import SimpleNamespace


from constants import RAG_REFUSAL_NO_CONTENT, RAG_REFUSAL_OUT_OF_RANGE
from rag.evaluation.custom_metrics import (
    DateCitationComplianceMetric,
    DateFilterHonoredMetric,
    DateGroundingMetric,
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

    def test_canonical_out_of_range_constant_is_recognised(self):
        """The metric must accept the exact out-of-range refusal string the
        MCP tool and REST handlers emit. Locks the constant <-> pattern coupling
        so the two can never drift apart silently."""
        metric = RefusalComplianceMetric()
        case = _make_case(actual_output=RAG_REFUSAL_OUT_OF_RANGE, must_refuse=True)
        assert metric.measure(case) == 1.0

    def test_canonical_no_content_constant_is_recognised(self):
        """The metric must accept the exact no-content refusal string."""
        metric = RefusalComplianceMetric()
        case = _make_case(actual_output=RAG_REFUSAL_NO_CONTENT, must_refuse=True)
        assert metric.measure(case) == 1.0


class TestDateGrounding:
    def test_no_ground_truth_is_vacuous_pass(self):
        """Absent expected_source_dates means grounding isn't evaluated — it must
        NOT silently report a green score; it passes vacuously and says so."""
        metric = DateGroundingMetric()
        case = _make_case(citations=[{"source_id": "nl_1", "source_date_start": "2026-03-01"}])
        assert metric.measure(case) == 1.0
        assert "not evaluated" in metric.reason

    def test_correct_grounding_passes(self):
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2026-03-01", "nl_2": "2026-04-10"},
            citations=[
                {"source_id": "nl_1", "source_date_start": "2026-03-01"},
                {"source_id": "nl_2", "source_date_start": "2026-04-10"},
            ],
        )
        assert metric.measure(case) == 1.0
        assert metric.success is True

    def test_wrong_stored_date_fails(self):
        """A chunk whose stored date disagrees with the true source date fails,
        even though it would pass DateFilterHonored and DateCitationCompliance."""
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2026-03-01", "nl_2": "2026-04-10"},
            citations=[
                {"source_id": "nl_1", "source_date_start": "2026-03-01"},
                {"source_id": "nl_2", "source_date_start": "2026-01-10"},  # corrupted
            ],
        )
        assert metric.measure(case) == 0.5
        assert metric.success is False

    def test_within_tolerance_passes(self):
        """Newsletters span a multi-day window; a start one day off the true date
        is within the default tolerance and must not false-fail."""
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2026-03-01"},
            citations=[{"source_id": "nl_1", "source_date_start": "2026-03-02"}],
        )
        assert metric.measure(case) == 1.0

    def test_falls_back_to_source_title_key(self):
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"LangTalks 2026-03": "2026-03-01"},
            citations=[{"source_title": "LangTalks 2026-03", "source_date_start": "2026-03-01"}],
        )
        assert metric.measure(case) == 1.0

    def test_citation_without_ground_truth_is_skipped(self):
        """A citation with no matching ground-truth entry is skipped, not failed;
        only the one with a known-true date is scored."""
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2026-03-01"},
            citations=[
                {"source_id": "nl_1", "source_date_start": "2026-03-01"},
                {"source_id": "nl_unknown", "source_date_start": "2026-09-09"},
            ],
        )
        assert metric.measure(case) == 1.0

    def test_tz_aware_stored_vs_naive_ground_truth(self):
        """Production stores source_date_start as tz-aware UTC while golden-set
        ground truth is authored naive. The metric must compare them without a
        naive/aware TypeError — this is the real ingest-vs-golden path."""
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2025-03-01"},  # naive
            citations=[{"source_id": "nl_1", "source_date_start": "2025-03-01T00:00:00+00:00"}],  # aware
        )
        assert metric.measure(case) == 1.0
        assert metric.success is True

    def test_tz_aware_stored_wrong_date_still_fails(self):
        """The tz coercion must not mask a genuinely wrong aware date."""
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2025-03-01"},
            citations=[{"source_id": "nl_1", "source_date_start": "2024-01-01T00:00:00+00:00"}],
        )
        assert metric.measure(case) == 0.0
        assert metric.success is False

    def test_no_citation_matches_ground_truth_is_vacuous_pass(self):
        metric = DateGroundingMetric()
        case = _make_case(
            expected_source_dates={"nl_1": "2026-03-01"},
            citations=[{"source_id": "nl_other", "source_date_start": "2026-03-01"}],
        )
        assert metric.measure(case) == 1.0
        assert "not evaluated" in metric.reason
