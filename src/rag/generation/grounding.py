"""
Answer Grounding Guards

Two defenses against parametric hallucination in the RAG answer path:

1. Evidence gate (pre-generation): when the best retrieved chunk's ABSOLUTE
   relevance (`evidence_score`, the normalized vector cosine) is below the
   configured floor, the caller must refuse instead of generating. Retrieval
   can always return *something*; weakly-related chunks invite the LLM to
   answer from its own knowledge while appearing grounded.

2. Date-tag grounding check (post-generation): every `[date: YYYY-MM-DD]` /
   `[dates: A to B]` tag the model emitted must fall inside the date range of
   at least one retrieved citation. A fabricated date tag is the signature of
   a parametric answer dressed up as a cited one — worse than a refusal.

Shared by the MCP rag_query tool, the REST chat handlers, and the LangGraph
conversation node so every generation surface enforces identical grounding.
"""

import logging
import re
from datetime import date, datetime

from constants import RAG_EVIDENCE_SCORE_FIELD

logger = logging.getLogger(__name__)

# Matches [date: 2026-03-21] and [dates: 2026-03-01 to 2026-03-21] (also the
# degenerate [dates: <single>] the model occasionally emits). Case-insensitive,
# whitespace-tolerant — mirrors the eval-side pattern in custom_metrics.
_DATE_TAG_PATTERN = re.compile(
    r"\[\s*dates?\s*:\s*(\d{4}-\d{2}-\d{2})(?:\s+to\s+(\d{4}-\d{2}-\d{2}))?\s*\]",
    re.IGNORECASE,
)

_CITATION_DATE_START_KEY = "source_date_start"
_CITATION_DATE_END_KEY = "source_date_end"


def max_evidence_score(citations: list[dict]) -> float:
    """Return the best absolute relevance score across citations (0.0 if none)."""
    if not citations:
        return 0.0
    return max(float(c.get(RAG_EVIDENCE_SCORE_FIELD, 0.0) or 0.0) for c in citations)


def is_evidence_sufficient(citations: list[dict], min_score: float) -> bool:
    """Whether retrieved evidence is strong enough to justify generating an answer.

    `min_score` <= 0 disables the gate (backward-compatible default). Otherwise
    at least one citation must carry an absolute `evidence_score` at or above
    the floor.
    """
    if min_score <= 0.0:
        return True
    if not citations:
        return False
    return max_evidence_score(citations) >= min_score


def find_ungrounded_date_tags(answer: str, citations: list[dict]) -> list[str]:
    """Return the date tags in `answer` not covered by any citation's date range.

    A tag is grounded when its date (or, for a range tag, BOTH endpoints) falls
    within [source_date_start, source_date_end] of at least one citation
    (date-granular, inclusive). Returns the offending tag strings verbatim so
    callers can log exactly what the model fabricated; empty list = grounded.
    """
    tags = list(_DATE_TAG_PATTERN.finditer(answer))
    if not tags:
        return []

    ranges = _citation_date_ranges(citations)
    ungrounded: list[str] = []
    for match in tags:
        tag_dates = [_parse_iso_date(match.group(1))]
        if match.group(2):
            tag_dates.append(_parse_iso_date(match.group(2)))
        if any(d is None for d in tag_dates):
            ungrounded.append(match.group(0))
            continue
        if not all(_date_in_any_range(d, ranges) for d in tag_dates):
            ungrounded.append(match.group(0))
    return ungrounded


def _citation_date_ranges(citations: list[dict]) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    for citation in citations:
        start = _parse_iso_date(citation.get(_CITATION_DATE_START_KEY))
        end = _parse_iso_date(citation.get(_CITATION_DATE_END_KEY))
        if start is None and end is None:
            continue
        start = start or end
        end = end or start
        ranges.append((min(start, end), max(start, end)))
    return ranges


def _date_in_any_range(value: date, ranges: list[tuple[date, date]]) -> bool:
    return any(start <= value <= end for start, end in ranges)


def _parse_iso_date(value) -> date | None:
    """Parse a date from an ISO string (date or datetime) or datetime; None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        logger.warning(f"Unparseable citation/tag date: '{text[:30]}'")
        return None
