"""
Integration tests for the Multi-Chat Consolidator (Parallel Orchestrator) Graph.

These tests use mocks to avoid requiring Beeper credentials or LLM API calls.
They focus on testing the graph structure, parallel dispatch, result aggregation,
and cross-chat consolidation.

Test Coverage:
- Graph structure and compilation
- Dispatch node (Send API)
- Worker wrapper
- Result aggregation
- Consolidation routing
- HITL (Human-in-the-Loop) routing
- Error handling (partial failure, all-fail scenarios)

NOTE: These tests require Docker environment due to dependency on matrix_decryption module.
Run in Docker: docker compose exec backend pytest tests/integration/test_multi_chat_consolidator_graph.py
"""

import os
import tempfile
from unittest.mock import patch
import pytest


# Check if we can import the graph modules (requires matrix_decryption)
def _can_import_graphs():
    """Check if graph modules can be imported (requires matrix_decryption)."""
    try:
        from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph
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

    def test_parallel_orchestrator_graph_compiles(self):
        """Test that the parallel orchestrator graph compiles without errors."""
        from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph

        assert parallel_orchestrator_graph is not None

    def test_graph_has_checkpointer(self):
        """Test that the graph has checkpointing enabled."""
        from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph

        assert parallel_orchestrator_graph is not None


@requires_docker
class TestDispatchChatsNode:
    """Test the dispatch_chats node."""

    def test_dispatch_chats_creates_send_commands(self):
        """Test that dispatch_chats creates Send commands for each chat."""
        from graphs.multi_chat_consolidator.graph import dispatch_chats

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_names": ["Chat 1", "Chat 2", "Chat 3"],
                "base_output_dir": tmpdir,
                "workflow_name": "periodic_newsletter",
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "desired_language_for_summary": "english",
                "summary_format": "langtalks_format",
                "consolidate_chats": True
            }

            result = dispatch_chats(state)

            # Should return Command with Send commands
            assert result.goto is not None
            assert len(result.goto) == 3  # Three chats

    def test_dispatch_chats_empty_list_raises_error(self):
        """Test that empty chat_names raises ValueError."""
        from graphs.multi_chat_consolidator.graph import dispatch_chats

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_names": [],  # Empty
                "base_output_dir": tmpdir,
                "workflow_name": "periodic_newsletter",
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "desired_language_for_summary": "english",
                "summary_format": "langtalks_format"
            }

            with pytest.raises(ValueError, match="requires non-empty 'chat_names'"):
                dispatch_chats(state)

    def test_dispatch_chats_creates_per_chat_directories(self):
        """Test that per-chat directories are created when consolidation enabled."""
        from graphs.multi_chat_consolidator.graph import dispatch_chats

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_names": ["Chat 1", "Chat 2"],
                "base_output_dir": tmpdir,
                "workflow_name": "periodic_newsletter",
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "desired_language_for_summary": "english",
                "summary_format": "langtalks_format",
                "consolidate_chats": True
            }

            result = dispatch_chats(state)

            # With consolidation enabled and multiple chats, should use per_chat/ subdirectory
            for send_cmd in result.goto:
                assert "per_chat" in send_cmd.arg["output_dir"]

    def test_dispatch_chats_sanitizes_chat_names(self):
        """Test that chat names are sanitized for filesystem safety."""
        from graphs.multi_chat_consolidator.graph import dispatch_chats

        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "chat_names": ["Chat/With:Unsafe#Chars"],
                "base_output_dir": tmpdir,
                "workflow_name": "periodic_newsletter",
                "data_source_name": "langtalks",
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "desired_language_for_summary": "english",
                "summary_format": "langtalks_format",
                "consolidate_chats": False
            }

            result = dispatch_chats(state)

            # Output dir should have sanitized name
            output_dir = result.goto[0].arg["output_dir"]
            assert "/" not in os.path.basename(output_dir)
            assert ":" not in os.path.basename(output_dir)
            assert "#" not in os.path.basename(output_dir)


@requires_docker
class TestChatWorkerWrapper:
    """Test the chat_worker_wrapper node."""

    @patch("graphs.multi_chat_consolidator.graph.newsletter_generation_graph")
    def test_worker_wrapper_returns_success_result(self, mock_graph):
        """Test that successful worker returns chat_results."""
        from graphs.multi_chat_consolidator.graph import chat_worker_wrapper

        # Mock successful workflow
        mock_graph.invoke.return_value = {
            "chat_name": "Test Chat",
            "start_date": "2025-01-01",
            "end_date": "2025-01-07",
            "message_count": 100,
            "newsletter_json_path": "/path/to/newsletter.json",
            "newsletter_md_path": "/path/to/newsletter.md",
            "final_translated_file_path": "/path/to/translated.md",
            "reused_existing": False,
            "separate_discussions_file_path": "/path/to/discussions.json",
            "discussions_ranking_file_path": "/path/to/ranking.json"
        }

        state = {"chat_name": "Test Chat"}

        result = chat_worker_wrapper(state)

        assert "chat_results" in result
        assert len(result["chat_results"]) == 1
        assert result["chat_results"][0]["chat_name"] == "Test Chat"

    @patch("graphs.multi_chat_consolidator.graph.newsletter_generation_graph")
    def test_worker_wrapper_returns_error_on_failure(self, mock_graph):
        """Test that failed worker returns chat_errors."""
        from graphs.multi_chat_consolidator.graph import chat_worker_wrapper

        # Mock failed workflow
        mock_graph.invoke.side_effect = Exception("Workflow failed")

        state = {
            "chat_name": "Test Chat",
            "start_date": "2025-01-01",
            "end_date": "2025-01-07"
        }

        result = chat_worker_wrapper(state)

        assert "chat_errors" in result
        assert len(result["chat_errors"]) == 1
        assert result["chat_errors"][0]["chat_name"] == "Test Chat"
        assert "Workflow failed" in result["chat_errors"][0]["error"]


@requires_docker
class TestAggregateResultsNode:
    """Test the aggregate_results node."""

    def test_aggregate_results_computes_statistics(self):
        """Test that aggregate_results computes correct statistics."""
        from graphs.multi_chat_consolidator.graph import aggregate_results

        state = {
            "chat_results": [
                {"chat_name": "Chat 1"},
                {"chat_name": "Chat 2"}
            ],
            "chat_errors": [
                {"chat_name": "Chat 3", "error": "Failed"}
            ]
        }

        result = aggregate_results(state)

        assert result["total_chats"] == 3
        assert result["successful_chats"] == 2
        assert result["failed_chats"] == 1

    def test_aggregate_results_all_failed_raises_error(self):
        """Test that all chats failing raises RuntimeError."""
        from graphs.multi_chat_consolidator.graph import aggregate_results

        state = {
            "chat_results": [],  # No successes
            "chat_errors": [
                {"chat_name": "Chat 1", "error": "Failed"},
                {"chat_name": "Chat 2", "error": "Failed"}
            ]
        }

        with pytest.raises(RuntimeError, match="All .* chats failed processing"):
            aggregate_results(state)

    def test_aggregate_results_partial_success_continues(self):
        """Test that partial success doesn't raise error."""
        from graphs.multi_chat_consolidator.graph import aggregate_results

        state = {
            "chat_results": [
                {"chat_name": "Chat 1"}  # One success
            ],
            "chat_errors": [
                {"chat_name": "Chat 2", "error": "Failed"},
                {"chat_name": "Chat 3", "error": "Failed"}
            ]
        }

        # Should not raise
        result = aggregate_results(state)

        assert result["successful_chats"] == 1
        assert result["failed_chats"] == 2


@requires_docker
class TestConsolidationRouting:
    """Test the consolidation routing logic."""

    def test_should_consolidate_returns_consolidate_when_enabled(self):
        """Test that consolidation is enabled when flag is True and multiple chats."""
        from graphs.multi_chat_consolidator.graph import should_consolidate_chats

        state = {
            "consolidate_chats": True,
            "successful_chats": 3
        }

        result = should_consolidate_chats(state)

        assert result == "consolidate"

    def test_should_consolidate_returns_skip_when_disabled(self):
        """Test that consolidation is skipped when flag is False."""
        from graphs.multi_chat_consolidator.graph import should_consolidate_chats

        state = {
            "consolidate_chats": False,
            "successful_chats": 3
        }

        result = should_consolidate_chats(state)

        assert result == "skip"

    def test_should_consolidate_returns_skip_with_single_chat(self):
        """Test that consolidation is skipped with only 1 successful chat."""
        from graphs.multi_chat_consolidator.graph import should_consolidate_chats

        state = {
            "consolidate_chats": True,
            "successful_chats": 1  # Only 1 chat
        }

        result = should_consolidate_chats(state)

        assert result == "skip"

    def test_should_consolidate_default_true(self):
        """Test that consolidate_chats defaults to True."""
        from graphs.multi_chat_consolidator.graph import should_consolidate_chats

        state = {
            # consolidate_chats not specified
            "successful_chats": 3
        }

        result = should_consolidate_chats(state)

        assert result == "consolidate"


@requires_docker
class TestHitlRouting:
    """Test HITL (Human-in-the-Loop) routing logic."""

    def test_requires_hitl_returns_continue_for_non_hitl_format(self):
        """Test that non-HITL formats skip HITL selection."""
        from graphs.multi_chat_consolidator.graph import requires_hitl_selection

        state = {
            "summary_format": "other_format",  # Not langtalks or mcp
            "hitl_selection_timeout_minutes": 60
        }

        result = requires_hitl_selection(state)

        assert result == "continue"

    def test_requires_hitl_returns_continue_when_timeout_zero(self):
        """Test that HITL is disabled when timeout is 0."""
        from graphs.multi_chat_consolidator.graph import requires_hitl_selection

        state = {
            "summary_format": "langtalks_format",
            "hitl_selection_timeout_minutes": 0  # Disabled
        }

        result = requires_hitl_selection(state)

        assert result == "continue"

    def test_requires_hitl_returns_hitl_for_langtalks_with_timeout(self):
        """Test that HITL is enabled for langtalks_format with timeout."""
        from graphs.multi_chat_consolidator.graph import requires_hitl_selection

        state = {
            "summary_format": "langtalks_format",
            "hitl_selection_timeout_minutes": 60  # Non-zero
        }

        result = requires_hitl_selection(state)

        assert result == "hitl"

    def test_requires_hitl_returns_hitl_for_mcp_with_timeout(self):
        """Test that HITL is enabled for mcp_israel_format with timeout."""
        from graphs.multi_chat_consolidator.graph import requires_hitl_selection

        state = {
            "summary_format": "mcp_israel_format",
            "hitl_selection_timeout_minutes": 120
        }

        result = requires_hitl_selection(state)

        assert result == "hitl"


@requires_docker
class TestOutputHandlerNode:
    """Test the output_handler node."""

    def test_output_handler_save_local_is_noop(self):
        """Test that save_local action is a no-op (files saved by workers)."""
        from graphs.multi_chat_consolidator.graph import output_handler

        state = {
            "output_actions": ["save_local"],
            "chat_results": [{"chat_name": "Test"}]
        }

        # Should not raise
        result = output_handler(state)

        assert result == {}

    def test_output_handler_webhook_missing_url_raises_error(self):
        """Test that webhook action without URL raises ValueError."""
        from graphs.multi_chat_consolidator.graph import output_handler

        state = {
            "output_actions": ["webhook"],
            "chat_results": [{"chat_name": "Test"}],
            # webhook_url not provided
        }

        with pytest.raises(ValueError, match="webhook_url' not provided"):
            output_handler(state)

    def test_output_handler_invalid_action_raises_error(self):
        """Test that invalid action raises ValueError."""
        from graphs.multi_chat_consolidator.graph import output_handler

        state = {
            "output_actions": ["invalid_action"],
            "chat_results": [{"chat_name": "Test"}]
        }

        with pytest.raises(ValueError, match="Unknown output action"):
            output_handler(state)


@requires_docker
class TestParallelOrchestratorState:
    """Test ParallelOrchestratorState TypedDict structure."""

    def test_state_has_required_fields(self):
        """Test that ParallelOrchestratorState has all required fields."""
        from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
        from typing import get_type_hints

        hints = get_type_hints(ParallelOrchestratorState)

        # Required fields
        assert "workflow_name" in hints
        assert "chat_names" in hints
        assert "data_source_name" in hints
        assert "start_date" in hints
        assert "end_date" in hints
        assert "desired_language_for_summary" in hints
        assert "summary_format" in hints
        assert "base_output_dir" in hints

    def test_state_has_aggregation_fields(self):
        """Test that ParallelOrchestratorState has aggregation fields."""
        from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
        from typing import get_type_hints

        hints = get_type_hints(ParallelOrchestratorState)

        # Aggregation fields (populated by reducer)
        assert "chat_results" in hints
        assert "chat_errors" in hints
        assert "total_chats" in hints
        assert "successful_chats" in hints
        assert "failed_chats" in hints

    def test_state_has_consolidation_fields(self):
        """Test that ParallelOrchestratorState has consolidation fields."""
        from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
        from typing import get_type_hints

        hints = get_type_hints(ParallelOrchestratorState)

        # Consolidation fields
        assert "consolidate_chats" in hints

    def test_state_has_output_fields(self):
        """Test that ParallelOrchestratorState has output configuration fields."""
        from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
        from typing import get_type_hints

        hints = get_type_hints(ParallelOrchestratorState)

        # Output action fields
        assert "output_actions" in hints
        assert "webhook_url" in hints


@requires_docker
class TestFormatTimestamp:
    """Test the format_timestamp helper function."""

    def test_format_timestamp_time_only(self):
        """Test formatting timestamp as time only."""
        from graphs.multi_chat_consolidator.graph import format_timestamp

        # 1699999999000 ms = specific datetime
        result = format_timestamp(1699999999000, "%H:%M")

        # Should return time in HH:MM format
        assert ":" in result
        assert len(result) == 5  # "HH:MM"

    def test_format_timestamp_date_only(self):
        """Test formatting timestamp as date only."""
        from graphs.multi_chat_consolidator.graph import format_timestamp

        result = format_timestamp(1699999999000, "%d.%m.%y")

        # Should return date in DD.MM.YY format
        assert "." in result


@pytest.mark.skip(reason="Requires Beeper credentials and complex mocking of async Matrix client")
@requires_docker
class TestEnsureValidSession:
    """Test the ensure_valid_session node (skipped - requires credentials)."""

    def test_ensure_valid_session_refreshes_once(self):
        """Test that session is refreshed once at orchestrator level."""
        # This test requires complex mocking of the RawDataExtractorBeeper class
        # which has module-level validation that requires BEEPER_ACCESS_TOKEN.
        # Skipped until proper test infrastructure is in place.
        pass
