"""Unit tests for the answer grounding guards (rag.generation.grounding).

Covers the two hallucination defenses added after the podcast-MCP verification
found the generator fabricating a non-ingested episode with fake date tags:
the pre-generation evidence gate and the post-generation date-tag check.
"""

from constants import RAG_EVIDENCE_SCORE_FIELD
from rag.generation.grounding import (
    find_ungrounded_date_tags,
    is_evidence_sufficient,
    max_evidence_score,
)


def _citation(score: float = 0.7, start: str = "2026-03-21", end: str | None = None) -> dict:
    return {
        RAG_EVIDENCE_SCORE_FIELD: score,
        "source_date_start": start,
        "source_date_end": end or start,
    }


class TestEvidenceGate:
    def test_disabled_gate_always_passes(self):
        assert is_evidence_sufficient([], min_score=0.0)
        assert is_evidence_sufficient([_citation(0.01)], min_score=0.0)

    def test_no_citations_fails_when_enabled(self):
        assert not is_evidence_sufficient([], min_score=0.6)

    def test_best_citation_at_floor_passes(self):
        assert is_evidence_sufficient([_citation(0.4), _citation(0.6)], min_score=0.6)

    def test_all_citations_below_floor_fails(self):
        assert not is_evidence_sufficient([_citation(0.55), _citation(0.58)], min_score=0.6)

    def test_missing_score_treated_as_zero(self):
        citation = {"source_date_start": "2026-03-21", "source_date_end": "2026-03-21"}
        assert max_evidence_score([citation]) == 0.0
        assert not is_evidence_sufficient([citation], min_score=0.1)

    def test_none_score_treated_as_zero(self):
        citation = _citation()
        citation[RAG_EVIDENCE_SCORE_FIELD] = None
        assert max_evidence_score([citation]) == 0.0


class TestDateTagGrounding:
    def test_answer_without_tags_is_grounded(self):
        assert find_ungrounded_date_tags("A plain answer.", [_citation()]) == []

    def test_grounded_single_date_tag(self):
        answer = "Asaf discussed AI SRE [1] [date: 2026-03-21]."
        assert find_ungrounded_date_tags(answer, [_citation(start="2026-03-21")]) == []

    def test_fabricated_date_tag_detected(self):
        # The exact failure mode from the verification: an invented episode date
        # outside every citation's range.
        answer = "The Lemonade episode covered barge-in latency [1] [date: 2026-01-18]."
        ungrounded = find_ungrounded_date_tags(answer, [_citation(start="2026-03-21")])
        assert ungrounded == ["[date: 2026-01-18]"]

    def test_range_tag_grounded_within_citation_range(self):
        answer = "Discussed across the window [dates: 2026-03-10 to 2026-03-20]."
        citation = _citation(start="2026-03-01", end="2026-03-31")
        assert find_ungrounded_date_tags(answer, [citation]) == []

    def test_range_tag_with_one_endpoint_outside_is_ungrounded(self):
        answer = "Covered over time [dates: 2026-03-10 to 2026-04-20]."
        citation = _citation(start="2026-03-01", end="2026-03-31")
        assert find_ungrounded_date_tags(answer, [citation]) == ["[dates: 2026-03-10 to 2026-04-20]"]

    def test_grounded_against_any_of_multiple_citations(self):
        answer = "One claim [date: 2026-03-21] and another [date: 2026-04-27]."
        citations = [_citation(start="2026-03-21"), _citation(start="2026-04-27")]
        assert find_ungrounded_date_tags(answer, citations) == []

    def test_tag_with_no_citations_is_ungrounded(self):
        answer = "Claim [date: 2026-03-21]."
        assert find_ungrounded_date_tags(answer, []) == ["[date: 2026-03-21]"]

    def test_case_and_whitespace_tolerant(self):
        answer = "Claim [ Date : 2026-03-21 ]."
        assert find_ungrounded_date_tags(answer, [_citation(start="2026-03-21")]) == []

    def test_datetime_iso_strings_in_citations(self):
        answer = "Claim [date: 2026-03-21]."
        citation = _citation()
        citation["source_date_start"] = "2026-03-21T00:00:00+00:00"
        citation["source_date_end"] = "2026-03-21T00:00:00+00:00"
        assert find_ungrounded_date_tags(answer, [citation]) == []

    def test_citation_with_null_dates_grounds_nothing(self):
        answer = "Claim [date: 2026-03-21]."
        citation = _citation()
        citation["source_date_start"] = None
        citation["source_date_end"] = None
        assert find_ungrounded_date_tags(answer, [citation]) == ["[date: 2026-03-21]"]
