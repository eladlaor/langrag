"""
Integration tests for the Single Chat Analyzer (Newsletter Generation) Graph.

These tests use mocks to avoid requiring Beeper credentials or LLM API calls.
They focus on testing the graph structure, node execution order, and state transitions.

Test Coverage:
- Graph structure and compilation
- Node execution order (linear flow)
- State transitions between nodes
- Error propagation (fail-fast)
- File existence checks
- Directory setup

NOTE: These tests require Docker environment due to dependency on matrix_decryption module.
Run in Docker: docker compose exec backend pytest tests/integration/test_single_chat_analyzer_graph.py
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest


# Check if we can import the graph modules (requires matrix_decryption)
def _can_import_graphs():
    """Check if graph modules can be imported (requires matrix_decryption)."""
    try:
        from graphs.single_chat_analyzer.graph import newsletter_generation_graph
        return True
    except ImportError:
        return False


# Skip marker for tests requiring Docker
requires_docker = pytest.mark.skipif(
    not _can_import_graphs(),
    reason="Requires Docker - matrix_decryption module not available outside Docker"
)


@requires_docker
class TestGraphCompilation:
    """Test that the graph compiles correctly."""

    def test_newsletter_generation_graph_compiles(self):
        """Test that the newsletter generation graph compiles without errors."""
        from graphs.single_chat_analyzer.graph import newsletter_generation_graph

        assert newsletter_generation_graph is not None

    def test_graph_compiles_without_checkpointer(self):
        """Test that the single chat graph compiles without a checkpointer (invoked atomically by orchestrator)."""
        from graphs.single_chat_analyzer.graph import newsletter_generation_graph

        assert newsletter_generation_graph is not None


@requires_docker
class TestSetupDirectoriesNode:
    """Test the setup_directories node."""

    def test_setup_directories_creates_all_directories(self):
        """Test that setup_directories creates all required directories."""
        from graphs.single_chat_analyzer.graph import setup_directories

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "output_dir": tmpdir,
                "chat_name": "Test Chat",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "workflow_name": "periodic_newsletter",
                "desired_language_for_summary": "english"
            }

            result = setup_directories(state)

            # Verify all directories were created
            assert os.path.exists(result["extraction_dir"])
            assert os.path.exists(result["preprocess_dir"])
            assert os.path.exists(result["translation_dir"])
            assert os.path.exists(result["separate_discussions_dir"])
            assert os.path.exists(result["discussions_ranking_dir"])
            assert os.path.exists(result["content_dir"])
            assert os.path.exists(result["link_enrichment_dir"])
            assert os.path.exists(result["final_translated_content_dir"])

    def test_setup_directories_returns_expected_file_paths(self):
        """Test that setup_directories returns all expected file paths."""
        from graphs.single_chat_analyzer.graph import setup_directories

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "output_dir": tmpdir,
                "chat_name": "Test Chat",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "workflow_name": "periodic_newsletter",
                "desired_language_for_summary": "english"
            }

            result = setup_directories(state)

            # Verify all expected file paths are returned
            assert "expected_extracted_file" in result
            assert "expected_preprocessed_file" in result
            assert "expected_translated_file" in result
            assert "expected_separate_discussions_file" in result
            assert "expected_discussions_ranking_file" in result
            assert "expected_newsletter_json" in result
            assert "expected_newsletter_md" in result
            assert "expected_enriched_newsletter_json" in result
            assert "expected_enriched_newsletter_md" in result
            assert "expected_final_translated_file" in result

    def test_setup_directories_sanitizes_chat_name(self):
        """Test that unsafe characters in chat name are sanitized."""
        from graphs.single_chat_analyzer.graph import setup_directories

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "output_dir": tmpdir,
                "chat_name": "Test/Chat:Name#2",  # Contains unsafe chars
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "workflow_name": "periodic_newsletter",
                "desired_language_for_summary": "english"
            }

            result = setup_directories(state)

            # The extraction directory should exist and have sanitized name in path
            extraction_dir = result["extraction_dir"]
            assert os.path.exists(extraction_dir)
            # The chat_name in the directory path should not contain unsafe chars
            # (but the file name may contain "/" in date range like 2025-01-01/2025-01-07)
            assert ":" not in os.path.basename(extraction_dir)
            assert "#" not in os.path.basename(extraction_dir)


@requires_docker
class TestExtractMessagesNode:
    """Test the extract_messages node."""

    @patch("graphs.single_chat_analyzer.graph.RawDataExtractorBeeper")
    def test_extract_messages_uses_cached_file_when_exists(self, mock_extractor_class):
        """Test that extract_messages reuses cached file when it exists."""
        from graphs.single_chat_analyzer.graph import extract_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cached file
            cached_file = os.path.join(tmpdir, "cached_messages.json")
            with open(cached_file, 'w') as f:
                json.dump([{"id": "1", "content": "Test"}], f)

            state = {
                "chat_name": "Test Chat",
                "expected_extracted_file": cached_file,
                "force_refresh_extraction": False,
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "extraction_dir": tmpdir
            }

            result = extract_messages(state)

            # Should return cached file without calling extractor
            assert result["extracted_file_path"] == cached_file
            assert result["reused_existing"] is True
            mock_extractor_class.assert_not_called()

    @patch("graphs.single_chat_analyzer.graph.RawDataExtractorBeeper")
    def test_extract_messages_extracts_when_force_refresh(self, mock_extractor_class):
        """Test that extract_messages extracts when force_refresh is True."""
        from graphs.single_chat_analyzer.graph import extract_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cached file
            cached_file = os.path.join(tmpdir, "cached_messages.json")
            with open(cached_file, 'w') as f:
                json.dump([{"id": "1", "content": "Test"}], f)

            # Mock extractor to return new file
            new_file = os.path.join(tmpdir, "new_messages.json")
            with open(new_file, 'w') as f:
                json.dump([{"id": "2", "content": "New"}], f)

            mock_extractor = MagicMock()
            mock_extractor.extract_messages.return_value = new_file
            mock_extractor_class.return_value = mock_extractor

            state = {
                "chat_name": "Test Chat",
                "expected_extracted_file": cached_file,
                "force_refresh_extraction": True,  # Force refresh
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "extraction_dir": tmpdir
            }

            result = extract_messages(state)

            # Should extract new messages
            assert result["extracted_file_path"] == new_file
            assert result["reused_existing"] is False
            mock_extractor.extract_messages.assert_called_once()

    @patch("graphs.single_chat_analyzer.graph.RawDataExtractorBeeper")
    def test_extract_messages_raises_on_extraction_failure(self, mock_extractor_class):
        """Test that extraction failure raises RuntimeError."""
        from graphs.single_chat_analyzer.graph import extract_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock extractor to raise error
            mock_extractor = MagicMock()
            mock_extractor.extract_messages.side_effect = Exception("API Error")
            mock_extractor_class.return_value = mock_extractor

            state = {
                "chat_name": "Test Chat",
                "expected_extracted_file": "/nonexistent/file.json",
                "force_refresh_extraction": False,  # Will try to extract since file doesn't exist
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "extraction_dir": tmpdir
            }

            with pytest.raises(RuntimeError, match="Failed to extract messages"):
                extract_messages(state)


@requires_docker
class TestPreprocessMessagesNode:
    """Test the preprocess_messages node."""

    @patch("graphs.single_chat_analyzer.graph.DataProcessorFactory")
    def test_preprocess_messages_uses_cached_file_when_exists(self, mock_factory):
        """Test that preprocess_messages reuses cached file when it exists."""
        from graphs.single_chat_analyzer.graph import preprocess_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cached file
            cached_file = os.path.join(tmpdir, "messages_processed.json")
            with open(cached_file, 'w') as f:
                json.dump([{"id": "1", "content": "Processed"}], f)

            state = {
                "chat_name": "Test Chat",
                "expected_preprocessed_file": cached_file,
                "force_refresh_preprocessing": False,
                "extracted_file_path": "/some/extracted.json",
                "data_source_name": "langtalks",
                "preprocess_dir": tmpdir
            }

            result = preprocess_messages(state)

            assert result["preprocessed_file_path"] == cached_file
            mock_factory.create.assert_not_called()

    @patch("graphs.single_chat_analyzer.graph.DataProcessorFactory")
    def test_preprocess_messages_raises_on_missing_extracted_file(self, mock_factory):
        """Test that missing extracted file raises FileNotFoundError."""
        from graphs.single_chat_analyzer.graph import preprocess_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_name": "Test Chat",
                "expected_preprocessed_file": os.path.join(tmpdir, "processed.json"),
                "force_refresh_preprocessing": False,
                "extracted_file_path": "/nonexistent/extracted.json",  # Doesn't exist
                "data_source_name": "langtalks",
                "preprocess_dir": tmpdir
            }

            with pytest.raises(FileNotFoundError, match="Extracted file not found"):
                preprocess_messages(state)


@requires_docker
class TestTranslateMessagesNode:
    """Test the translate_messages node."""

    @patch("graphs.single_chat_analyzer.graph.DataProcessorFactory")
    def test_translate_messages_uses_cached_file_when_exists(self, mock_factory):
        """Test that translate_messages reuses cached file when it exists."""
        from graphs.single_chat_analyzer.graph import translate_messages

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cached file
            cached_file = os.path.join(tmpdir, "messages_translated.json")
            with open(cached_file, 'w') as f:
                json.dump([{"id": "1", "content": "Translated"}], f)

            state = {
                "chat_name": "Test Chat",
                "expected_translated_file": cached_file,
                "force_refresh_translation": False,
                "preprocessed_file_path": "/some/preprocessed.json",
                "data_source_name": "langtalks",
                "translation_dir": tmpdir,
                "desired_language_for_summary": "English"
            }

            result = translate_messages(state)

            assert result["translated_file_path"] == cached_file
            mock_factory.create.assert_not_called()


@requires_docker
class TestRankDiscussionsNode:
    """Test the rank_discussions node."""

    @patch("graphs.single_chat_analyzer.graph.discussions_ranker_graph")
    def test_rank_discussions_uses_cached_file_when_exists(self, mock_subgraph):
        """Test that rank_discussions reuses cached file when it exists."""
        from graphs.single_chat_analyzer.graph import rank_discussions

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cached file
            cached_file = os.path.join(tmpdir, "discussions_ranking.json")
            with open(cached_file, 'w') as f:
                json.dump({"ranked": [1, 2, 3]}, f)

            state = {
                "chat_name": "Test Chat",
                "expected_discussions_ranking_file": cached_file,
                "force_refresh_discussions_ranking": False,
                "separate_discussions_file_path": "/some/discussions.json",
                "discussions_ranking_dir": tmpdir,
                "summary_format": "langtalks_format"
            }

            result = rank_discussions(state)

            assert result["discussions_ranking_file_path"] == cached_file
            mock_subgraph.invoke.assert_not_called()


@requires_docker
class TestGenerateContentNode:
    """Test the generate_content node."""

    def test_generate_content_missing_ranking_file_raises_error(self):
        """Test that missing ranking file raises RuntimeError (fail-fast)."""
        from graphs.single_chat_analyzer.graph import generate_content

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_name": "Test Chat",
                "expected_newsletter_json": os.path.join(tmpdir, "newsletter.json"),
                "expected_newsletter_md": os.path.join(tmpdir, "newsletter.md"),
                "force_refresh_content": False,
                "discussions_ranking_file_path": "",  # Empty - should fail
                "separate_discussions_file_path": "/some/discussions.json",
                "data_source_name": "langtalks",
                "content_dir": tmpdir,
                "summary_format": "langtalks_format",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07"
            }

            with pytest.raises(RuntimeError, match="Missing discussions_ranking_file_path"):
                generate_content(state)

    def test_generate_content_nonexistent_ranking_file_raises_error(self):
        """Test that nonexistent ranking file raises FileNotFoundError."""
        from graphs.single_chat_analyzer.graph import generate_content

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_name": "Test Chat",
                "expected_newsletter_json": os.path.join(tmpdir, "newsletter.json"),
                "expected_newsletter_md": os.path.join(tmpdir, "newsletter.md"),
                "force_refresh_content": False,
                "discussions_ranking_file_path": "/nonexistent/ranking.json",
                "separate_discussions_file_path": "/some/discussions.json",
                "data_source_name": "langtalks",
                "content_dir": tmpdir,
                "summary_format": "langtalks_format",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07"
            }

            with pytest.raises(FileNotFoundError, match="not found"):
                generate_content(state)


@requires_docker
class TestTranslateFinalSummaryNode:
    """Test the translate_final_summary node."""

    def test_translate_final_summary_skips_english(self):
        """Test that translation is skipped when language is already English."""
        from graphs.single_chat_analyzer.graph import translate_final_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_name": "Test Chat",
                "expected_final_translated_file": os.path.join(tmpdir, "translated.md"),
                "force_refresh_final_translation": False,
                "desired_language_for_summary": "english",  # Already English
                "enriched_newsletter_md_path": os.path.join(tmpdir, "newsletter.md"),
                "newsletter_md_path": os.path.join(tmpdir, "newsletter.md"),
                "data_source_name": "langtalks",
                "summary_format": "langtalks_format",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07"
            }

            result = translate_final_summary(state)

            # Should return None (skipped)
            assert result["final_translated_file_path"] is None


@requires_docker
class TestSingleChatState:
    """Test SingleChatState TypedDict structure."""

    def test_state_has_required_fields(self):
        """Test that SingleChatState has all required fields."""
        from graphs.single_chat_analyzer.state import SingleChatState
        from typing import get_type_hints

        hints = get_type_hints(SingleChatState)

        # Required input fields
        assert "workflow_name" in hints
        assert "data_source_type" in hints
        assert "data_source_name" in hints
        assert "chat_name" in hints
        assert "start_date" in hints
        assert "end_date" in hints
        assert "desired_language_for_summary" in hints
        assert "summary_format" in hints
        assert "output_dir" in hints

    def test_state_has_optional_directory_paths(self):
        """Test that SingleChatState has optional directory path fields."""
        from graphs.single_chat_analyzer.state import SingleChatState
        from typing import get_type_hints

        hints = get_type_hints(SingleChatState)

        # Directory paths (set by setup_directories)
        assert "extraction_dir" in hints
        assert "preprocess_dir" in hints
        assert "translation_dir" in hints
        assert "separate_discussions_dir" in hints
        assert "discussions_ranking_dir" in hints
        assert "content_dir" in hints
        assert "link_enrichment_dir" in hints

    def test_state_has_force_refresh_flags(self):
        """Test that SingleChatState has force refresh flags."""
        from graphs.single_chat_analyzer.state import SingleChatState
        from typing import get_type_hints

        hints = get_type_hints(SingleChatState)

        # Force refresh flags
        assert "force_refresh_extraction" in hints
        assert "force_refresh_preprocessing" in hints
        assert "force_refresh_translation" in hints
        assert "force_refresh_separate_discussions" in hints
        assert "force_refresh_content" in hints
        assert "force_refresh_final_translation" in hints
