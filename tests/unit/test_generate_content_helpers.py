"""
Unit tests for generate_content helper functions.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from graphs.single_chat_analyzer.generate_content_helpers import (
    validate_ranking_file,
    validate_discussions_file,
    load_ranking_data,
    load_featured_discussions,
    generate_newsletter_id,
    initialize_mongodb_repository,
    validate_content_generation_output,
    load_newsletter_for_evaluation,
    score_newsletter_if_available,
    log_mongodb_persistence_success,
)


class TestValidateRankingFile:
    """Tests for validate_ranking_file function."""

    def test_raises_runtime_error_when_empty_path(self):
        """Empty ranking_file path raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Missing discussions_ranking_file_path"):
            validate_ranking_file("", "Test Chat")

    def test_raises_file_not_found_when_missing(self, tmp_path):
        """Non-existent file raises FileNotFoundError."""
        fake_path = str(tmp_path / "nonexistent.json")

        with pytest.raises(FileNotFoundError, match="not found"):
            validate_ranking_file(fake_path, "Test Chat")

    def test_passes_when_file_exists(self, tmp_path):
        """No exception when file exists."""
        ranking_file = tmp_path / "ranking.json"
        ranking_file.write_text("{}")

        # Should not raise
        validate_ranking_file(str(ranking_file), "Test Chat")


class TestValidateDiscussionsFile:
    """Tests for validate_discussions_file function."""

    def test_raises_file_not_found_when_missing(self, tmp_path):
        """Non-existent file raises FileNotFoundError."""
        fake_path = str(tmp_path / "nonexistent.json")

        with pytest.raises(FileNotFoundError, match="not found"):
            validate_discussions_file(fake_path)

    def test_passes_when_file_exists(self, tmp_path):
        """No exception when file exists."""
        discussions_file = tmp_path / "discussions.json"
        discussions_file.write_text("[]")

        # Should not raise
        validate_discussions_file(str(discussions_file))


class TestLoadRankingData:
    """Tests for load_ranking_data function."""

    def test_raises_when_featured_ids_missing(self, tmp_path):
        """RuntimeError when featured_discussion_ids is missing."""
        ranking_file = tmp_path / "ranking.json"
        ranking_file.write_text(json.dumps({"brief_mention_items": []}))

        with pytest.raises(RuntimeError, match="missing 'featured_discussion_ids'"):
            load_ranking_data(str(ranking_file), "Test Chat")

    def test_raises_when_featured_ids_empty(self, tmp_path):
        """RuntimeError when featured_discussion_ids is empty list."""
        ranking_file = tmp_path / "ranking.json"
        ranking_file.write_text(json.dumps({
            "featured_discussion_ids": [],
            "brief_mention_items": []
        }))

        with pytest.raises(RuntimeError, match="No featured_discussion_ids"):
            load_ranking_data(str(ranking_file), "Test Chat")

    def test_returns_ids_and_brief_mentions(self, tmp_path):
        """Returns featured IDs and brief mention items."""
        ranking_file = tmp_path / "ranking.json"
        ranking_file.write_text(json.dumps({
            "featured_discussion_ids": ["id1", "id2"],
            "brief_mention_items": [{"text": "mention1"}]
        }))

        ids, briefs = load_ranking_data(str(ranking_file), "Test Chat")

        assert ids == ["id1", "id2"]
        assert briefs == [{"text": "mention1"}]


class TestLoadFeaturedDiscussions:
    """Tests for load_featured_discussions function."""

    def test_filters_discussions_by_id(self, tmp_path):
        """Only returns discussions matching featured IDs."""
        discussions_file = tmp_path / "discussions.json"
        discussions_file.write_text(json.dumps({
            "discussions": [
                {"id": "d1", "title": "First"},
                {"id": "d2", "title": "Second"},
                {"id": "d3", "title": "Third"}
            ]
        }))

        result = load_featured_discussions(
            str(discussions_file),
            ["d1", "d3"],
            "Test Chat"
        )

        assert len(result) == 2
        assert result[0]["id"] == "d1"
        assert result[1]["id"] == "d3"

    def test_raises_when_no_matches(self, tmp_path):
        """RuntimeError when no discussions match featured IDs."""
        discussions_file = tmp_path / "discussions.json"
        discussions_file.write_text(json.dumps({
            "discussions": [
                {"id": "d1", "title": "First"}
            ]
        }))

        with pytest.raises(RuntimeError, match="No matching discussions"):
            load_featured_discussions(
                str(discussions_file),
                ["nonexistent_id"],
                "Test Chat"
            )


class TestGenerateNewsletterId:
    """Tests for generate_newsletter_id function."""

    def test_basic_id_generation(self):
        """Generates ID with correct format."""
        result = generate_newsletter_id("run_123", "Test Chat")

        assert result == "run_123_nl_test_chat"

    def test_special_characters_stripped(self):
        """Special characters are converted to underscores."""
        result = generate_newsletter_id("run_456", "MCP Israel #2!")

        assert "mcp_israel" in result
        assert "#" not in result
        assert "!" not in result


class TestInitializeMongodbRepository:
    """Tests for initialize_mongodb_repository function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_run_id(self):
        """Returns (None, None) when mongodb_run_id is None."""
        repo, newsletter_id = await initialize_mongodb_repository(None, "Test Chat")

        assert repo is None
        assert newsletter_id is None

    @pytest.mark.asyncio
    async def test_handles_initialization_error(self):
        """Returns (None, None) on initialization error."""
        with patch('db.connection.get_database') as mock_db:
            mock_db.side_effect = Exception("Connection failed")

            repo, newsletter_id = await initialize_mongodb_repository("run_123", "Test")

        assert repo is None
        assert newsletter_id is None


class TestValidateContentGenerationOutput:
    """Tests for validate_content_generation_output function."""

    def test_raises_when_no_result(self):
        """RuntimeError when content_result is None."""
        with pytest.raises(RuntimeError, match="no result"):
            validate_content_generation_output(
                content_result=None,
                result_newsletter_id=None,
                newsletter_json_path=None,
                newsletter_md_path=None,
                state={}
            )

    def test_raises_when_legacy_files_missing(self, tmp_path):
        """RuntimeError in legacy mode when files don't exist."""
        with pytest.raises(RuntimeError, match="did not create"):
            validate_content_generation_output(
                content_result={"some": "result"},
                result_newsletter_id=None,  # Legacy mode
                newsletter_json_path=str(tmp_path / "nonexistent.json"),
                newsletter_md_path=str(tmp_path / "nonexistent.md"),
                state={}
            )


class TestLoadNewsletterForEvaluation:
    """Tests for load_newsletter_for_evaluation function."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_available(self):
        """Returns empty dict when no sources available."""
        result = await load_newsletter_for_evaluation(
            result_newsletter_id=None,
            newsletters_repo=None,
            newsletter_json_path=None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_loads_from_file_when_available(self, tmp_path):
        """Loads from file when path exists."""
        json_file = tmp_path / "newsletter.json"
        json_file.write_text(json.dumps({"title": "Test Newsletter"}))

        result = await load_newsletter_for_evaluation(
            result_newsletter_id=None,
            newsletters_repo=None,
            newsletter_json_path=str(json_file)
        )

        assert result == {"title": "Test Newsletter"}


class TestScoreNewsletterIfAvailable:
    """Tests for score_newsletter_if_available function."""

    def test_does_nothing_when_no_span(self):
        """No action when span is None."""
        # Should not raise
        score_newsletter_if_available(
            span=None,
            newsletter_result={"content": "test"},
            trace_id="trace_123"
        )

    def test_does_nothing_when_no_result(self):
        """No action when newsletter_result is empty."""
        mock_span = MagicMock()

        # Should not raise
        score_newsletter_if_available(
            span=mock_span,
            newsletter_result={},
            trace_id="trace_123"
        )


class TestLogMongodbPersistenceSuccess:
    """Tests for log_mongodb_persistence_success function."""

    def test_logs_when_id_provided(self, caplog):
        """Logs success message when newsletter_id is provided."""
        import logging

        with caplog.at_level(logging.INFO):
            log_mongodb_persistence_success("nl_123")

        assert "nl_123" in caplog.text
        assert "persisted" in caplog.text.lower()

    def test_does_nothing_when_no_id(self, caplog):
        """No logging when newsletter_id is None."""
        import logging

        with caplog.at_level(logging.INFO):
            log_mongodb_persistence_success(None)

        assert "persisted" not in caplog.text.lower()
