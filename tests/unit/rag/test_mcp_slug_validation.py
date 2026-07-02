"""Podcast slug tool-boundary validation tests (M2) — no Docker."""

import pytest

from constants import MCP_PODCAST_SLUG_MAX_LENGTH
from rag.mcp.validation import MCPToolInputError, validate_podcast_slug


def test_none_passes_through():
    assert validate_podcast_slug(None) is None


@pytest.mark.parametrize("slug", ["langtalks", "mcp-israel", "a", "show-2", "n8n-israel-main-1"])
def test_valid_kebab_slugs(slug):
    assert validate_podcast_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "   ",
        "Uppercase",
        "has space",
        "under_score",
        "trailing-",
        "-leading",
        "sql'injection",
        "slug;drop",
        "emoji😀",
        "a" * (MCP_PODCAST_SLUG_MAX_LENGTH + 1),
    ],
)
def test_invalid_slugs_rejected(slug):
    with pytest.raises(MCPToolInputError):
        validate_podcast_slug(slug)
