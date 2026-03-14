"""
Unit tests for discussions_ranker subgraph.

Test Coverage:
- analyze_discussions node function
- Graph construction and compilation

NOTE: Tests require Docker environment due to import dependencies.
Run in Docker: docker compose exec backend pytest tests/unit/subgraphs/test_discussions_ranker.py
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from tests.unit.subgraphs.conftest import requires_docker


@requires_docker
class TestAnalyzeDiscussionsNode:
    """Test analyze_discussions node function."""

    @pytest.mark.asyncio
    async def test_analyze_existing_file_skips_processing(self):
        """Test that existing ranking file is reused."""
        from graphs.subgraphs.discussions_ranker import analyze_discussions

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create existing ranking file
            expected_file = os.path.join(temp_dir, "ranking.json")
            with open(expected_file, 'w') as f:
                json.dump({"ranked_discussions": []}, f)

            state = {
                "expected_discussions_ranking_file": expected_file,
                "force_refresh_discussions_ranking": False,
                "separate_discussions_file_path": "/unused/path.json",
                "summary_format": "langtalks_format"
            }

            result = await analyze_discussions(state)

            assert result["discussions_ranking_file_path"] == expected_file

    @pytest.mark.asyncio
    async def test_analyze_force_refresh_reprocesses(self):
        """Test that force_refresh bypasses existing file."""
        from graphs.subgraphs.discussions_ranker import analyze_discussions

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create existing ranking file
            expected_file = os.path.join(temp_dir, "ranking.json")
            with open(expected_file, 'w') as f:
                json.dump({"old": "data"}, f)

            # Create discussions file with empty discussions
            discussions_path = os.path.join(temp_dir, "discussions.json")
            with open(discussions_path, 'w') as f:
                json.dump({"discussions": []}, f)

            state = {
                "expected_discussions_ranking_file": expected_file,
                "force_refresh_discussions_ranking": True,
                "separate_discussions_file_path": discussions_path,
                "summary_format": "langtalks_format"
            }

            result = await analyze_discussions(state)

            # Should create new file
            assert result["discussions_ranking_file_path"] == expected_file

            # Verify content was updated (not old data)
            with open(expected_file, 'r') as f:
                data = json.load(f)
                assert "old" not in data

    @pytest.mark.asyncio
    async def test_analyze_empty_discussions_creates_empty_ranking(self):
        """Test that empty discussions list creates empty ranking."""
        from graphs.subgraphs.discussions_ranker import analyze_discussions

        with tempfile.TemporaryDirectory() as temp_dir:
            expected_file = os.path.join(temp_dir, "ranking.json")
            discussions_path = os.path.join(temp_dir, "discussions.json")

            with open(discussions_path, 'w') as f:
                json.dump({"discussions": []}, f)

            state = {
                "expected_discussions_ranking_file": expected_file,
                "force_refresh_discussions_ranking": False,
                "separate_discussions_file_path": discussions_path,
                "summary_format": "langtalks_format"
            }

            result = await analyze_discussions(state)

            with open(result["discussions_ranking_file_path"], 'r') as f:
                data = json.load(f)
                assert data["ranked_discussions"] == []
                assert data["editorial_notes"] == "No discussions to rank"

    @pytest.mark.asyncio
    @patch('graphs.subgraphs.discussions_ranker.rank_with_llm')
    @patch('graphs.subgraphs.discussions_ranker.load_previous_newsletters')
    async def test_analyze_with_discussions_calls_ranking(self, mock_load_prev, mock_rank_llm):
        """Test that discussions are ranked using LLM."""
        from graphs.subgraphs.discussions_ranker import analyze_discussions

        # Mock ranking result
        mock_rank_llm.return_value = {
            "ranked_discussions": [
                {"discussion_id": "disc_1", "rank": 1, "importance_score": 9.0}
            ],
            "editorial_notes": "Test ranking"
        }
        mock_load_prev.return_value = MagicMock(total_editions=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            expected_file = os.path.join(temp_dir, "ranking.json")
            discussions_path = os.path.join(temp_dir, "discussions.json")

            discussions_data = {
                "discussions": [
                    {
                        "id": "disc_1",
                        "title": "Test Discussion",
                        "nutshell": "Summary",
                        "num_messages": 10,
                        "num_unique_participants": 5
                    }
                ]
            }
            with open(discussions_path, 'w') as f:
                json.dump(discussions_data, f)

            state = {
                "expected_discussions_ranking_file": expected_file,
                "force_refresh_discussions_ranking": False,
                "separate_discussions_file_path": discussions_path,
                "summary_format": "langtalks_format",
                "top_k_discussions": 5,
                "previous_newsletters_to_consider": 5,
                "data_source_name": "langtalks",
                "current_start_date": "2025-01-01"
            }

            result = await analyze_discussions(state)

            mock_rank_llm.assert_called_once()
            assert os.path.exists(result["discussions_ranking_file_path"])


@requires_docker
class TestBuildDiscussionsRankerGraph:
    """Test discussions ranker graph construction."""

    def test_build_graph_compiles_successfully(self):
        """Test that graph builds and compiles without errors."""
        from graphs.subgraphs.discussions_ranker import build_discussions_ranker_graph

        graph = build_discussions_ranker_graph()

        assert graph is not None
        assert hasattr(graph, 'invoke')

    def test_exported_graph_exists(self):
        """Test that the exported graph is available."""
        from graphs.subgraphs.discussions_ranker import discussions_ranker_graph

        assert discussions_ranker_graph is not None
