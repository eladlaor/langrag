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

These metrics are deepeval-compatible (BaseMetric subclasses) so they slot into
the existing run_evaluation pipeline alongside the LLM-judge metrics.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable

logger = logging.getLogger(__name__)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Zא-תא-ת])|\n+")
_DATE_TAG = re.compile(r"\[\s*(?:date|dates)\s*:\s*\d{4}-\d{2}-\d{2}", re.IGNORECASE)
_CITATION_MARKER = re.compile(r"\[\s*\d+\s*\]")
_REFUSAL_PATTERNS = (
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
