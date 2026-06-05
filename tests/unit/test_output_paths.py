"""
Unit tests for periodic-newsletter output path construction and resolution.

Covers the per-community nested layout helpers in src/utils/output_paths.py:
- build_run_output_dir: writers emit <base>/<community>/<community>_<start>_to_<end>
- resolve_run_dir: readers resolve a run_id back to its nested path
- parse_run_id / community_of_run_id: round-trip and suffix tolerance
"""

import pytest

from utils.output_paths import (
    build_run_output_dir,
    community_of_run_id,
    parse_run_id,
    resolve_run_dir,
)

BASE = "output/generate_periodic_newsletter"


class TestBuildRunOutputDir:
    def test_nests_under_community(self):
        assert build_run_output_dir(BASE, "langtalks", "2025-10-01", "2025-10-26") == f"{BASE}/langtalks/langtalks_2025-10-01_to_2025-10-26"

    def test_multi_underscore_community(self):
        assert build_run_output_dir(BASE, "mcp_israel", "2025-01-01", "2025-01-15") == f"{BASE}/mcp_israel/mcp_israel_2025-01-01_to_2025-01-15"


class TestResolveRunDir:
    def test_resolves_to_nested_path(self):
        run_id = "n8n_israel_2025-12-20_to_2026-01-03"
        assert resolve_run_dir(BASE, run_id) == f"{BASE}/n8n_israel/{run_id}"

    def test_tolerates_trailing_suffix(self):
        run_id = "ail_2026-04-17_to_2026-05-10_merged"
        assert resolve_run_dir(BASE, run_id) == f"{BASE}/ail/{run_id}"

    def test_raises_on_malformed(self):
        with pytest.raises(ValueError):
            resolve_run_dir(BASE, "not-a-run-id")


class TestParseRunId:
    @pytest.mark.parametrize(
        "run_id,expected",
        [
            ("langtalks_2025-10-01_to_2025-10-26", ("langtalks", "2025-10-01", "2025-10-26")),
            ("mcp_israel_2026-02-01_to_2026-02-28", ("mcp_israel", "2026-02-01", "2026-02-28")),
            ("ail_ai_transformation_guild_consolidated_2026-05-11_to_2026-05-31", ("ail_ai_transformation_guild_consolidated", "2026-05-11", "2026-05-31")),
        ],
    )
    def test_round_trip(self, run_id, expected):
        assert parse_run_id(run_id) == expected

    def test_strict_rejects_trailing_suffix(self):
        # Strict parse does not accept a suffix after the end date.
        assert parse_run_id("ail_2026-04-17_to_2026-05-10_merged") is None

    def test_returns_none_on_garbage(self):
        assert parse_run_id("garbage") is None


class TestCommunityOfRunId:
    def test_extracts_community(self):
        assert community_of_run_id("langtalks_2025-10-01_to_2025-10-26") == "langtalks"

    def test_tolerates_trailing_suffix(self):
        assert community_of_run_id("mcp_israel_2026-04-05_to_2026-05-10_merged") == "mcp_israel"

    def test_returns_none_on_garbage(self):
        assert community_of_run_id("just_a_folder") is None
