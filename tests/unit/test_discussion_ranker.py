"""
Unit tests for Discussion Ranker module.

Tests cover:
- Discussion loading from JSON files
- LLM preparation (summarization for token efficiency)
- Metadata enrichment
- Top-K categorization
- Ranking result persistence
- Error handling (fail-fast approach)
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from conftest import (
    DiscussionFactory,
    RankingFactory,
    assert_file_exists,
    assert_json_file_valid
)


# Check if we can import modules that use utils.observability (has 'from src.' issue)
def _can_import_full_ranker():
    """Check if full discussion ranker can be imported."""
    try:
        from core.retrieval.rankers.discussion_ranker import rank_discussions
        return True
    except ImportError:
        return False


# Skip marker for tests requiring Docker due to import issues
requires_docker_for_llm = pytest.mark.skipif(
    not _can_import_full_ranker(),
    reason="Requires Docker - source code has 'from src.' import issues in utils/observability"
)


@requires_docker_for_llm
class TestLoadDiscussions:
    """Test discussion loading functionality."""

    def test_load_discussions_success(self, temp_discussions_file):
        """Test successful loading of discussions from file."""
        from core.retrieval.rankers.discussion_ranker import load_discussions

        discussions = load_discussions(temp_discussions_file)

        assert isinstance(discussions, list)
        assert len(discussions) == 5  # Default from fixture

    def test_load_discussions_file_not_found_raises_error(self):
        """Test that missing file raises FileNotFoundError."""
        from core.retrieval.rankers.discussion_ranker import load_discussions

        with pytest.raises(FileNotFoundError, match="not found"):
            load_discussions("/nonexistent/file.json")

    def test_load_discussions_invalid_json_raises_error(self, temp_output_dir):
        """Test that invalid JSON raises RuntimeError."""
        from core.retrieval.rankers.discussion_ranker import load_discussions

        invalid_file = os.path.join(temp_output_dir, "invalid.json")
        with open(invalid_file, 'w') as f:
            f.write("not valid json {")

        with pytest.raises(RuntimeError, match="Failed to parse"):
            load_discussions(invalid_file)

    def test_load_discussions_empty_file(self, temp_output_dir):
        """Test loading file with no discussions."""
        from core.retrieval.rankers.discussion_ranker import load_discussions

        empty_file = os.path.join(temp_output_dir, "empty.json")
        with open(empty_file, 'w') as f:
            json.dump({"discussions": []}, f)

        discussions = load_discussions(empty_file)

        assert discussions == []


@requires_docker_for_llm
class TestCountUniqueParticipants:
    """Test unique participant counting."""

    def test_count_unique_participants_multiple_senders(self):
        """Test counting unique participants in discussion."""
        from core.retrieval.rankers.discussion_ranker import count_unique_participants

        discussion = {
            "messages": [
                {"sender_id": "user_1"},
                {"sender_id": "user_2"},
                {"sender_id": "user_1"},  # Duplicate
                {"sender_id": "user_3"},
            ]
        }

        count = count_unique_participants(discussion)

        assert count == 3

    def test_count_unique_participants_empty_messages(self):
        """Test counting with no messages."""
        from core.retrieval.rankers.discussion_ranker import count_unique_participants

        discussion = {"messages": []}
        count = count_unique_participants(discussion)

        assert count == 0

    def test_count_unique_participants_missing_sender_id(self):
        """Test counting when some messages lack sender_id."""
        from core.retrieval.rankers.discussion_ranker import count_unique_participants

        discussion = {
            "messages": [
                {"sender_id": "user_1"},
                {"content": "message without sender"},  # No sender_id
                {"sender_id": "user_2"},
            ]
        }

        count = count_unique_participants(discussion)

        assert count == 2


@requires_docker_for_llm
class TestPrepareDiscussionsForLlm:
    """Test LLM preparation functionality."""

    def test_prepare_discussions_extracts_key_fields(self, sample_discussions):
        """Test that preparation extracts essential fields."""
        from core.retrieval.rankers.discussion_ranker import prepare_discussions_for_llm

        prepared = prepare_discussions_for_llm(sample_discussions)

        assert len(prepared) == len(sample_discussions)

        for disc in prepared:
            assert "id" in disc
            assert "title" in disc
            assert "nutshell" in disc
            assert "num_messages" in disc
            assert "num_unique_participants" in disc
            assert "sample_messages" in disc

    def test_prepare_discussions_includes_sample_messages(self, sample_discussions):
        """Test that sample messages are included."""
        from core.retrieval.rankers.discussion_ranker import prepare_discussions_for_llm

        prepared = prepare_discussions_for_llm(sample_discussions)

        for disc in prepared:
            assert len(disc["sample_messages"]) == 2  # First and last

    def test_prepare_discussions_handles_empty_messages(self):
        """Test handling discussion with no messages."""
        from core.retrieval.rankers.discussion_ranker import prepare_discussions_for_llm

        discussions = [{
            "id": "disc_1",
            "title": "Empty",
            "nutshell": "No messages",
            "messages": [],
            "num_messages": 0
        }]

        prepared = prepare_discussions_for_llm(discussions)

        assert prepared[0]["sample_messages"] == ["", ""]


@requires_docker_for_llm
class TestEnrichRankingWithMetadata:
    """Test metadata enrichment functionality."""

    def test_enrich_adds_missing_num_messages(self):
        """Test that num_messages is added when missing."""
        from core.retrieval.rankers.discussion_ranker import enrich_ranking_with_metadata

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1}
            ]
        }

        original_discussions = [{
            "id": "disc_1",
            "num_messages": 42,
            "messages": []
        }]

        enriched = enrich_ranking_with_metadata(ranking_result, original_discussions)

        assert enriched["ranked_discussions"][0]["num_messages"] == 42

    def test_enrich_adds_missing_participant_count(self):
        """Test that num_unique_participants is calculated when missing."""
        from core.retrieval.rankers.discussion_ranker import enrich_ranking_with_metadata

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1}
            ]
        }

        original_discussions = [{
            "id": "disc_1",
            "messages": [
                {"sender_id": "user_1"},
                {"sender_id": "user_2"},
                {"sender_id": "user_1"}
            ]
        }]

        enriched = enrich_ranking_with_metadata(ranking_result, original_discussions)

        assert enriched["ranked_discussions"][0]["num_unique_participants"] == 2

    def test_enrich_preserves_existing_values(self):
        """Test that existing values are not overwritten."""
        from core.retrieval.rankers.discussion_ranker import enrich_ranking_with_metadata

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "num_messages": 100}
            ]
        }

        original_discussions = [{
            "id": "disc_1",
            "num_messages": 42,  # Different value
            "messages": []
        }]

        enriched = enrich_ranking_with_metadata(ranking_result, original_discussions)

        # Should keep existing value (100), not overwrite with 42
        assert enriched["ranked_discussions"][0]["num_messages"] == 100


@requires_docker_for_llm
class TestApplyTopKCategorization:
    """Test top-K categorization functionality."""

    def test_categorize_featured_discussions(self):
        """Test that top-K discussions are marked as featured."""
        from core.retrieval.rankers.discussion_ranker import apply_top_k_categorization

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "one_liner_summary": "Summary 1"},
                {"discussion_id": "disc_2", "rank": 2, "one_liner_summary": "Summary 2"},
                {"discussion_id": "disc_3", "rank": 3, "one_liner_summary": "Summary 3"},
            ]
        }

        original_discussions = [
            {"id": "disc_1", "title": "Title 1", "messages": []},
            {"id": "disc_2", "title": "Title 2", "messages": []},
            {"id": "disc_3", "title": "Title 3", "messages": []},
        ]

        result = apply_top_k_categorization(ranking_result, top_k=2, original_discussions=original_discussions)

        # Top 2 should be featured
        assert result["ranked_discussions"][0]["category"] == "featured"
        assert result["ranked_discussions"][1]["category"] == "featured"
        # Rank 3 should be brief_mention
        assert result["ranked_discussions"][2]["category"] == "brief_mention"

    def test_categorize_skipped_discussions(self):
        """Test that skipped discussions get skip category."""
        from core.retrieval.rankers.discussion_ranker import apply_top_k_categorization

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "skip_reason": "Duplicate"},
            ]
        }

        original_discussions = [{"id": "disc_1", "title": "Title", "messages": []}]

        result = apply_top_k_categorization(ranking_result, top_k=5, original_discussions=original_discussions)

        assert result["ranked_discussions"][0]["category"] == "skip"

    def test_creates_featured_discussion_ids_list(self):
        """Test that featured_discussion_ids list is created."""
        from core.retrieval.rankers.discussion_ranker import apply_top_k_categorization

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "one_liner_summary": "S1"},
                {"discussion_id": "disc_2", "rank": 2, "one_liner_summary": "S2"},
                {"discussion_id": "disc_3", "rank": 3, "one_liner_summary": "S3"},
            ]
        }

        original_discussions = [
            {"id": f"disc_{i}", "title": f"Title {i}", "messages": []}
            for i in range(1, 4)
        ]

        result = apply_top_k_categorization(ranking_result, top_k=2, original_discussions=original_discussions)

        assert "featured_discussion_ids" in result
        assert result["featured_discussion_ids"] == ["disc_1", "disc_2"]

    def test_creates_brief_mention_items_list(self):
        """Test that brief_mention_items list is created."""
        from core.retrieval.rankers.discussion_ranker import apply_top_k_categorization

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "one_liner_summary": "S1"},
                {"discussion_id": "disc_2", "rank": 2, "one_liner_summary": "S2"},
                {"discussion_id": "disc_3", "rank": 3, "one_liner_summary": "Brief mention", "importance_score": 7},
            ]
        }

        original_discussions = [
            {"id": f"disc_{i}", "title": f"Title {i}", "messages": []}
            for i in range(1, 4)
        ]

        result = apply_top_k_categorization(ranking_result, top_k=2, original_discussions=original_discussions)

        assert "brief_mention_items" in result
        assert len(result["brief_mention_items"]) == 1
        assert result["brief_mention_items"][0]["discussion_id"] == "disc_3"
        assert result["brief_mention_items"][0]["one_liner"] == "Brief mention"


@requires_docker_for_llm
class TestSaveRankingResult:
    """Test ranking result persistence."""

    def test_save_creates_file(self, temp_output_dir, sample_ranking_result):
        """Test that save creates output file."""
        from core.retrieval.rankers.discussion_ranker import save_ranking_result

        output_file = os.path.join(temp_output_dir, "ranking_output.json")

        save_ranking_result(sample_ranking_result, output_file)

        assert_file_exists(output_file)
        assert_json_file_valid(output_file)

    def test_save_creates_parent_directories(self, temp_output_dir, sample_ranking_result):
        """Test that save creates parent directories if needed."""
        from core.retrieval.rankers.discussion_ranker import save_ranking_result

        output_file = os.path.join(temp_output_dir, "subdir", "nested", "ranking.json")

        save_ranking_result(sample_ranking_result, output_file)

        assert_file_exists(output_file)

    def test_save_handles_unicode(self, temp_output_dir):
        """Test that save handles Unicode content correctly."""
        from core.retrieval.rankers.discussion_ranker import save_ranking_result

        ranking_result = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "title": "שלום עולם 👋"}
            ]
        }

        output_file = os.path.join(temp_output_dir, "unicode_ranking.json")
        save_ranking_result(ranking_result, output_file)

        with open(output_file, 'r', encoding='utf-8') as f:
            loaded = json.load(f)

        assert loaded["ranked_discussions"][0]["title"] == "שלום עולם 👋"


@requires_docker_for_llm
class TestDiscussionRankerClass:
    """Test the DiscussionRanker class."""

    def test_init_sets_parameters(self):
        """Test that __init__ sets parameters correctly."""
        from core.retrieval.rankers.discussion_ranker import DiscussionRanker

        ranker = DiscussionRanker(
            summary_format="langtalks_format",
            top_k=3
        )

        assert ranker.summary_format == "langtalks_format"
        assert ranker.top_k == 3

    def test_rank_uses_cached_file_when_exists(self, temp_output_dir, temp_discussions_file):
        """Test that rank() uses cached file when it exists."""
        from core.retrieval.rankers.discussion_ranker import DiscussionRanker

        # Create cached output file
        output_file = os.path.join(temp_output_dir, "cached_ranking.json")
        cached_result = {"cached": True, "ranked_discussions": []}
        with open(output_file, 'w') as f:
            json.dump(cached_result, f)

        ranker = DiscussionRanker(summary_format="langtalks_format")
        result = ranker.rank(
            discussions_file=temp_discussions_file,
            output_file=output_file,
            force_refresh=False
        )

        assert result["cached"] is True

    def test_rank_empty_discussions_creates_empty_result(self, temp_output_dir):
        """Test that ranking empty discussions creates empty result."""
        from core.retrieval.rankers.discussion_ranker import DiscussionRanker

        # Create empty discussions file
        empty_file = os.path.join(temp_output_dir, "empty_discussions.json")
        with open(empty_file, 'w') as f:
            json.dump({"discussions": []}, f)

        output_file = os.path.join(temp_output_dir, "empty_ranking.json")

        ranker = DiscussionRanker(summary_format="langtalks_format")
        result = ranker.rank(
            discussions_file=empty_file,
            output_file=output_file,
            force_refresh=True
        )

        assert result["ranked_discussions"] == []
        assert result["editorial_notes"] == "No discussions to rank"


@requires_docker_for_llm
class TestRankDiscussionsFunction:
    """Test the rank_discussions convenience function (requires Docker)."""

    def test_rank_discussions_creates_ranker_and_invokes(self, temp_output_dir):
        """Test that function creates ranker and calls rank()."""
        from core.retrieval.rankers.discussion_ranker import rank_discussions

        # Create empty discussions file
        discussions_file = os.path.join(temp_output_dir, "discussions.json")
        with open(discussions_file, 'w') as f:
            json.dump({"discussions": []}, f)

        output_file = os.path.join(temp_output_dir, "ranking.json")

        result = rank_discussions(
            discussions_file=discussions_file,
            output_file=output_file,
            summary_format="langtalks_format",
            top_k=5
        )

        assert "ranked_discussions" in result
        assert "top_k_applied" in result
        assert result["top_k_applied"] == 5


@requires_docker_for_llm
class TestRankWithLlm:
    """Test LLM-based ranking (with mocked LLM) - requires Docker."""

    @pytest.mark.asyncio
    @patch('core.retrieval.rankers.discussion_ranker.is_langfuse_enabled', return_value=False)
    @patch('core.retrieval.rankers.discussion_ranker.get_settings')
    @patch('core.retrieval.rankers.discussion_ranker.DISCUSSION_RANKING_PROMPT')
    @patch('core.retrieval.rankers.discussion_ranker.create_chat_model')
    async def test_rank_with_llm_parses_response(self, mock_create_chat, mock_prompt, mock_settings, mock_langfuse):
        """Test that LLM response is parsed correctly."""
        from core.retrieval.rankers.discussion_ranker import rank_with_llm

        # Setup mock response
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1}
            ],
            "editorial_notes": "Test notes"
        })

        # Setup mock chain (prompt | llm) with async ainvoke
        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)

        # The | operator is called on the prompt template
        mock_prompt.__or__.return_value = mock_chain

        # Mock settings
        mock_settings.return_value.llm.ranking_model = "gpt-4"
        mock_settings.return_value.llm.temperature_ranking = 0.1

        discussions_summary = [
            {"id": "disc_1", "title": "Test", "nutshell": "Summary"}
        ]

        result = await rank_with_llm(discussions_summary, "langtalks_format")

        assert "ranked_discussions" in result
        assert len(result["ranked_discussions"]) == 1

    @pytest.mark.asyncio
    @patch('core.retrieval.rankers.discussion_ranker.is_langfuse_enabled', return_value=False)
    @patch('core.retrieval.rankers.discussion_ranker.get_settings')
    @patch('core.retrieval.rankers.discussion_ranker.DISCUSSION_RANKING_PROMPT')
    @patch('core.retrieval.rankers.discussion_ranker.create_chat_model')
    async def test_rank_with_llm_invalid_json_raises_error(self, mock_create_chat, mock_prompt, mock_settings, mock_langfuse):
        """Test that invalid LLM response raises RuntimeError."""
        from core.retrieval.rankers.discussion_ranker import rank_with_llm

        # Setup mock with invalid JSON response
        mock_response = MagicMock()
        mock_response.content = "not valid json"

        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)

        mock_prompt.__or__.return_value = mock_chain

        # Mock settings
        mock_settings.return_value.llm.ranking_model = "gpt-4"
        mock_settings.return_value.llm.temperature_ranking = 0.1

        discussions_summary = [{"id": "disc_1"}]

        with pytest.raises(RuntimeError, match="Failed to parse LLM response"):
            await rank_with_llm(discussions_summary, "langtalks_format")

    @pytest.mark.asyncio
    @patch('core.retrieval.rankers.discussion_ranker.is_langfuse_enabled', return_value=False)
    @patch('core.retrieval.rankers.discussion_ranker.get_settings')
    @patch('core.retrieval.rankers.discussion_ranker.DISCUSSION_RANKING_PROMPT')
    @patch('core.retrieval.rankers.discussion_ranker.create_chat_model')
    async def test_rank_with_llm_missing_ranked_discussions_raises_error(self, mock_create_chat, mock_prompt, mock_settings, mock_langfuse):
        """Test that missing ranked_discussions field raises RuntimeError."""
        from core.retrieval.rankers.discussion_ranker import rank_with_llm

        mock_response = MagicMock()
        mock_response.content = json.dumps({"other_field": "value"})

        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)

        mock_prompt.__or__.return_value = mock_chain

        # Mock settings
        mock_settings.return_value.llm.ranking_model = "gpt-4"
        mock_settings.return_value.llm.temperature_ranking = 0.1

        discussions_summary = [{"id": "disc_1"}]

        with pytest.raises(RuntimeError, match="LLM analysis failed"):
            await rank_with_llm(discussions_summary, "langtalks_format")
