"""
Custom RAG evaluation metrics.

Three metrics specific to the langrag.ai date-aware contract:

  - DateCitationComplianceMetric: every factual sentence in the answer must carry
    a [date: YYYY-MM-DD] or [dates: A to B] tag. Score = fraction of compliant
    sentences; pass threshold default 1.0 — partial compliance is a fail because
    the contract is non-negotiable.

  - DateFilterHonoredMetric: when the test case requested a date window, every
    citation's source_date_start..source_date_end must intersect that window.
    Score = fraction of in-window citations; threshold default 1.0.

  - RefusalComplianceMetric: when the test case is marked must_refuse=True,
    the answer must contain a refusal phrase (no in-range content found, etc.)
    rather than fabricating an answer. Score is 1.0 on a clean refusal else 0.0.

  - DateGroundingMetric: every citation's stored source_date_start must match the
    TRUE source date, derived independently of the chunk's own stored value. This
    is the distinction from DateFilterHonoredMetric — that metric only checks the
    stored tag lands inside the requested window, trusting the tag; this one checks
    the tag is itself correct against ground truth, catching ingestion-time date
    corruption (timezone drift, wrong-source cache keys) that the filter check
    cannot see. Ground truth comes from additional_metadata["expected_source_dates"],
    a {citation-key -> ISO date} map authored in the golden set (offline CI bar);
    the live integration variant derives it from the source-of-truth at eval time
    (see rag.evaluation.date_grounding.resolve_true_source_date).

These metrics are deepeval-compatible (BaseMetric subclasses) so they slot into
the CI eval gate (src/rag/evaluation/gate.py) alongside the LLM-judge metrics.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from collections.abc import Iterable

from constants import (
    RAG_DATE_GROUNDING_TOLERANCE_DAYS,
    RAG_REFUSAL_INSUFFICIENT_EVIDENCE,
    RAG_REFUSAL_NO_CONTENT,
    RAG_REFUSAL_OUT_OF_RANGE,
)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Zא-תא-ת])|\n+")
_DATE_TAG = re.compile(r"\[\s*(?:date|dates)\s*:\s*\d{4}-\d{2}-\d{2}", re.IGNORECASE)
_CITATION_MARKER = re.compile(r"\[\s*\d+\s*\]")
# Canonical refusal strings are the single source of truth (src/constants.py); the
# metric matches their lowercased full form so it can never stop recognising a real
# refusal emitted by the MCP tool / REST handlers. The remaining lenient patterns
# guard against LLM-phrased refusals and are intentionally broader.
_REFUSAL_PATTERNS = (
    RAG_REFUSAL_OUT_OF_RANGE.lower(),
    RAG_REFUSAL_NO_CONTENT.lower(),
    RAG_REFUSAL_INSUFFICIENT_EVIDENCE.lower(),
    "no content was found",
    "no in-range content",
    "no relevant content",
    "couldn't find",
    "could not find",
    "outside the requested",
    "broaden the date window",
    "broaden the window",
)


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _coerce_utc(value: datetime | None) -> datetime | None:
    """Normalise to tz-aware UTC so naive (golden-set) and aware (ingested) dates
    can be subtracted without a TypeError. Naive values are assumed UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _split_factual_sentences(answer: str) -> list[str]:
    """Return non-trivial sentences that look factual (carry a citation marker)."""
    if not answer:
        return []
    raw = _SENTENCE_SPLIT.split(answer.strip())
    return [s.strip() for s in raw if _CITATION_MARKER.search(s)]


try:  # pragma: no cover - exercised in env where deepeval is installed
    from deepeval.metrics.base_metric import BaseMetric
    from deepeval.test_case import LLMTestCase

    _DEEPEVAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    BaseMetric = object  # type: ignore[assignment,misc]
    LLMTestCase = object  # type: ignore[assignment,misc]
    _DEEPEVAL_AVAILABLE = False


class _AsyncCompatibleMetric(BaseMetric):  # type: ignore[misc]
    """Common scaffolding: pure-Python scoring, no LLM calls, deterministic."""

    evaluation_model = "rule-based"

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.score: float = 0.0
        self.reason: str = ""
        self.success: bool = False
        self.strict_mode: bool = False
        self.error: str | None = None

    @property
    def __name__(self) -> str:  # type: ignore[override]
        return self.__class__.__name__

    def is_successful(self) -> bool:
        return self.success

    async def a_measure(self, test_case, *args, **kwargs):  # type: ignore[override]
        return self.measure(test_case, *args, **kwargs)


class DateCitationComplianceMetric(_AsyncCompatibleMetric):
    """Every factual sentence in the answer must carry a [date: ...] tag."""

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:  # type: ignore[override]
        sentences = _split_factual_sentences(getattr(test_case, "actual_output", "") or "")
        if not sentences:
            self.score = 1.0
            self.reason = "Answer contained no cited factual sentences (vacuously compliant)."
            self.success = self.score >= self.threshold
            return self.score

        compliant = [s for s in sentences if _DATE_TAG.search(s)]
        self.score = len(compliant) / len(sentences)
        missing = [s for s in sentences if not _DATE_TAG.search(s)][:3]
        self.reason = (
            f"{len(compliant)}/{len(sentences)} cited sentences carried a date tag."
            + (f" Examples missing: {missing}" if missing else "")
        )
        self.success = self.score >= self.threshold
        return self.score


class DateFilterHonoredMetric(_AsyncCompatibleMetric):
    """Every citation must overlap the requested date window when one was supplied.

    Reads the requested window from test_case.additional_metadata['date_filter']
    (dict with optional date_start/date_end ISO strings) and the citations from
    test_case.additional_metadata['citations'] (list with source_date_start/end).
    """

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:  # type: ignore[override]
        meta = getattr(test_case, "additional_metadata", None) or {}
        date_filter = meta.get("date_filter") or {}
        ds = _to_datetime(date_filter.get("date_start"))
        de = _to_datetime(date_filter.get("date_end"))
        citations: Iterable[dict] = meta.get("citations") or []

        if ds is None and de is None:
            self.score = 1.0
            self.reason = "No date filter requested; metric vacuously passes."
            self.success = True
            return self.score

        in_window = 0
        out_of_window: list[dict] = []
        total = 0
        for cite in citations:
            total += 1
            cs = _to_datetime(cite.get("source_date_start"))
            ce = _to_datetime(cite.get("source_date_end")) or cs
            if cs is None or ce is None:
                out_of_window.append(cite)
                continue
            if de is not None and cs > de:
                out_of_window.append(cite)
                continue
            if ds is not None and ce < ds:
                out_of_window.append(cite)
                continue
            in_window += 1

        if total == 0:
            self.score = 1.0
            self.reason = "No citations to evaluate; metric vacuously passes."
            self.success = True
            return self.score

        self.score = in_window / total
        self.reason = (
            f"{in_window}/{total} citations fell within the requested window "
            f"({date_filter.get('date_start')} .. {date_filter.get('date_end')})."
        )
        self.success = self.score >= self.threshold
        return self.score


class RefusalComplianceMetric(_AsyncCompatibleMetric):
    """For test cases marked must_refuse=True, the answer must be a refusal."""

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:  # type: ignore[override]
        meta = getattr(test_case, "additional_metadata", None) or {}
        must_refuse = bool(meta.get("must_refuse"))
        answer = (getattr(test_case, "actual_output", "") or "").lower()

        if not must_refuse:
            self.score = 1.0
            self.reason = "Test case does not require a refusal; metric vacuously passes."
            self.success = True
            return self.score

        refused = any(p in answer for p in _REFUSAL_PATTERNS)
        self.score = 1.0 if refused else 0.0
        self.reason = "Refused as required." if refused else "Expected refusal, got an answer."
        self.success = self.score >= self.threshold
        return self.score


def _citation_key(cite: dict) -> str | None:
    """The stable key used to look a citation up in the expected_source_dates map.

    source_id uniquely identifies the source-of-truth (newsletter doc id / podcast
    file). source_title is the human-readable fallback the golden set is authored
    against when source_id isn't surfaced. Prefer the precise key, fall back to the
    title so an older golden set keyed by title still resolves.
    """
    return cite.get("source_id") or cite.get("source_title")


class DateGroundingMetric(_AsyncCompatibleMetric):
    """Every citation's stored date must match the TRUE source date.

    Unlike DateFilterHonoredMetric, which trusts the stored tag and only checks it
    falls inside the requested window, this metric checks the tag is *correct*. The
    ground-truth map (additional_metadata['expected_source_dates'], keyed by
    source_id or source_title -> ISO date) is derived independently of the chunk's
    stored value — from the golden set offline, or from the source-of-truth live —
    so a chunk stamped with the wrong date fails here even though it would sail
    through every other date metric.

    Score = fraction of citations whose source_date_start is within
    RAG_DATE_GROUNDING_TOLERANCE_DAYS of the true date. Citations with no ground
    truth available are skipped (not penalised) — absence of a known-true date is a
    golden-set gap, not a grounding failure. If NO citation has ground truth the
    metric passes vacuously and says so, so a missing map never masquerades as a
    green grounding score.
    """

    def __init__(self, threshold: float = 1.0, tolerance_days: int = RAG_DATE_GROUNDING_TOLERANCE_DAYS) -> None:
        super().__init__(threshold=threshold)
        self._tolerance = timedelta(days=tolerance_days)

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:  # type: ignore[override]
        meta = getattr(test_case, "additional_metadata", None) or {}
        expected: dict = meta.get("expected_source_dates") or {}
        citations: Iterable[dict] = meta.get("citations") or []

        if not expected:
            self.score = 1.0
            self.reason = "No ground-truth source dates supplied; grounding not evaluated (vacuous pass)."
            self.success = True
            return self.score

        checked = 0
        grounded = 0
        mismatches: list[str] = []
        for cite in citations:
            key = _citation_key(cite)
            true_raw = expected.get(key) if key is not None else None
            true_date = _coerce_utc(_to_datetime(true_raw))
            if true_date is None:
                continue
            # Ingestion stamps source_date_start as tz-aware UTC; golden-set ground
            # truth is authored naive ("2025-03-01"). Coerce both to UTC before
            # subtracting — a naive/aware mix would raise TypeError and crash the gate.
            stored = _coerce_utc(_to_datetime(cite.get("source_date_start")))
            checked += 1
            if stored is not None and abs(stored - true_date) <= self._tolerance:
                grounded += 1
            else:
                mismatches.append(
                    f"{key}: stored={cite.get('source_date_start')} true={true_raw}"
                )

        if checked == 0:
            self.score = 1.0
            self.reason = "No citation matched a ground-truth entry; grounding not evaluated (vacuous pass)."
            self.success = True
            return self.score

        self.score = grounded / checked
        self.reason = (
            f"{grounded}/{checked} citations correctly grounded to their true source date "
            f"(±{self._tolerance.days}d)."
            + (f" Mismatches: {mismatches[:3]}" if mismatches else "")
        )
        self.success = self.score >= self.threshold
        return self.score
