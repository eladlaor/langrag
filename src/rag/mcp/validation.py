"""
Tool-boundary input validation for the MCP search surface.

This surface is public and probed adversarially, so tool inputs are a
resource-exhaustion lever. Every guard here runs at the tool boundary BEFORE any
expensive work (embedding, vector search): reject over-long queries, clamp
top_k to a hard max, and reject inverted/absurd date ranges with a clear error
instead of silently truncating or driving a pointless retrieval.
"""

import logging
import re

from constants import (
    MCP_DATE_MAX_YEAR,
    MCP_PODCAST_SLUG_MAX_LENGTH,
    MCP_PODCAST_SLUG_PATTERN,
    MCP_QUERY_MAX_LENGTH,
    MCP_TOP_K_HARD_MAX,
)

logger = logging.getLogger(__name__)

_PODCAST_SLUG_RE = re.compile(MCP_PODCAST_SLUG_PATTERN)


class MCPToolInputError(ValueError):
    """Raised when an MCP tool input violates a boundary constraint.

    A distinct type (not a bare ValueError) so callers/tests can assert on the
    security-boundary rejection specifically, and so the FastMCP layer surfaces
    it as a clean tool error rather than an internal fault.
    """


def validate_query(query: str) -> str:
    """Validate and return the query text.

    Rejects an empty or over-long query with an explicit error rather than
    silently truncating a large payload at embedding time (memory + a wasted
    embedding call).
    """
    if not query or not query.strip():
        raise MCPToolInputError("query must be a non-empty string.")
    if len(query) > MCP_QUERY_MAX_LENGTH:
        logger.warning(
            "Rejected over-long MCP query",
            extra={"query_length": len(query), "max_length": MCP_QUERY_MAX_LENGTH},
        )
        raise MCPToolInputError(f"query is too long ({len(query)} chars); max is {MCP_QUERY_MAX_LENGTH}.")
    return query


def clamp_top_k(top_k: int | None) -> int | None:
    """Clamp top_k to the hard max at the tool boundary.

    None passes through (retrieval falls back to the config default). A negative
    or zero value is rejected. A value above the hard max is clamped down (not
    rejected) so an over-eager caller still gets results, just bounded.
    """
    if top_k is None:
        return None
    if top_k <= 0:
        raise MCPToolInputError(f"top_k must be a positive integer, got {top_k}.")
    if top_k > MCP_TOP_K_HARD_MAX:
        logger.warning(
            "Clamped MCP top_k to hard max",
            extra={"requested_top_k": top_k, "hard_max": MCP_TOP_K_HARD_MAX},
        )
        return MCP_TOP_K_HARD_MAX
    return top_k


def validate_podcast_slug(slug: str | None) -> str | None:
    """Validate the optional `podcast` slug filter at the tool boundary.

    The slug flows into a Mongo equality filter, so it is validated like every
    other public input rather than trusted as free text: None passes through
    (search all podcasts); otherwise it must be a bounded, lowercase kebab-case
    identifier. An over-long or malformed value is rejected (not silently coerced)
    so an adversarial caller cannot smuggle arbitrary strings into the query.
    """
    if slug is None:
        return None
    if not slug.strip():
        raise MCPToolInputError("podcast slug must be a non-empty string when provided.")
    if len(slug) > MCP_PODCAST_SLUG_MAX_LENGTH:
        logger.warning(
            "Rejected over-long MCP podcast slug",
            extra={"slug_length": len(slug), "max_length": MCP_PODCAST_SLUG_MAX_LENGTH},
        )
        raise MCPToolInputError(f"podcast slug is too long ({len(slug)} chars); max is {MCP_PODCAST_SLUG_MAX_LENGTH}.")
    if not _PODCAST_SLUG_RE.match(slug):
        raise MCPToolInputError(f"podcast slug '{slug}' is malformed; expected lowercase letters, digits, and hyphens (kebab-case).")
    return slug


def validate_date_range(date_start, date_end) -> None:
    """Reject inverted and absurd date ranges.

    Called AFTER the ISO-format parse. `_parse_iso_date` validates format only;
    this adds sanity: date_start must not exceed date_end, and neither may be
    beyond MCP_DATE_MAX_YEAR (a year-9999 style garbage bound).
    """
    if date_start is not None and date_end is not None and date_start > date_end:
        raise MCPToolInputError(f"Inverted date range: date_start ({date_start.date().isoformat()}) is after date_end ({date_end.date().isoformat()}).")
    for label, value in (("date_start", date_start), ("date_end", date_end)):
        if value is not None and value.year > MCP_DATE_MAX_YEAR:
            raise MCPToolInputError(f"Absurd {label}: year {value.year} exceeds the maximum plausible year {MCP_DATE_MAX_YEAR}.")
