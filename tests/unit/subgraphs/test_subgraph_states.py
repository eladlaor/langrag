"""
Unit tests for subgraph state schemas.

Test Coverage:
- DiscussionRankerState TypedDict
- LinkEnricherState TypedDict

NOTE: Tests require Docker environment due to import dependencies.
Run in Docker: docker compose exec backend pytest tests/unit/subgraphs/test_subgraph_states.py
"""

from typing import get_origin, Annotated

from tests.unit.subgraphs.conftest import requires_docker


@requires_docker
class TestDiscussionRankerState:
    """Test DiscussionRankerState TypedDict."""

    def test_state_has_required_fields(self):
        """Test that state schema has expected fields."""
        from graphs.subgraphs.state import DiscussionRankerState

        # Check required fields exist in TypedDict
        annotations = DiscussionRankerState.__annotations__

        assert "separate_discussions_file_path" in annotations
        assert "discussions_ranking_dir" in annotations
        assert "expected_discussions_ranking_file" in annotations
        assert "summary_format" in annotations
        assert "top_k_discussions" in annotations
        assert "discussions_ranking_file_path" in annotations


@requires_docker
class TestLinkEnricherState:
    """Test LinkEnricherState TypedDict."""

    def test_state_has_required_fields(self):
        """Test that state schema has expected fields."""
        from graphs.subgraphs.state import LinkEnricherState

        annotations = LinkEnricherState.__annotations__

        assert "separate_discussions_file_path" in annotations
        assert "newsletter_json_path" in annotations
        assert "link_enrichment_dir" in annotations
        assert "summary_format" in annotations
        assert "extracted_links" in annotations
        assert "searched_links" in annotations

    def test_state_has_reducer_annotations(self):
        """Test that accumulator fields have Annotated reducer types."""
        from graphs.subgraphs.state import LinkEnricherState

        annotations = LinkEnricherState.__annotations__

        # extracted_links and searched_links should be Annotated with operator.add
        # This is a simplified check - just verify they are Annotated
        extracted_type = annotations["extracted_links"]
        searched_type = annotations["searched_links"]

        # In Python's typing, Annotated types have __origin__ of Annotated
        assert get_origin(extracted_type) is Annotated
        assert get_origin(searched_type) is Annotated
