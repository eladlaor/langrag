"""
Unit tests for constants module.
"""

import pytest

from constants import (
    # Newsletter constants
    NewsletterVersionType,
    NewsletterType,
    DiscussionCategory,
    RepetitionScore,
    SimilarityThreshold,
    # Stage enums
    PipelineStage,
    StageStatus,
    ProgressEventType,
    # LLM enums
    LLMCallType,
    # Route constants
    API_V1_PREFIX,
    ROUTE_GENERATE_PERIODIC_NEWSLETTER,
    # HTTP status codes
    HTTP_STATUS_OK,
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NOT_FOUND,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    # Timeout constants
    TIMEOUT_HTTP_REQUEST,
    TIMEOUT_CACHE_OPERATION,
    # Community structure
    KNOWN_WHATSAPP_CHAT_NAMES,
    COMMUNITY_STRUCTURE,
)


class TestNewsletterVersionType:
    """Tests for NewsletterVersionType enum."""

    def test_original_value(self):
        """ORIGINAL value is correct."""
        assert NewsletterVersionType.ORIGINAL.value == "original"
        assert str(NewsletterVersionType.ORIGINAL) == "original"

    def test_enriched_value(self):
        """ENRICHED value is correct."""
        assert NewsletterVersionType.ENRICHED.value == "enriched"

    def test_translated_value(self):
        """TRANSLATED value is correct."""
        assert NewsletterVersionType.TRANSLATED.value == "translated"

    def test_all_values_are_strings(self):
        """All enum values are strings for JSON serialization."""
        for version in NewsletterVersionType:
            assert isinstance(version.value, str)


class TestNewsletterType:
    """Tests for NewsletterType enum."""

    def test_per_chat_value(self):
        """PER_CHAT value is correct."""
        assert NewsletterType.PER_CHAT.value == "per_chat"

    def test_consolidated_value(self):
        """CONSOLIDATED value is correct."""
        assert NewsletterType.CONSOLIDATED.value == "consolidated"


class TestDiscussionCategory:
    """Tests for DiscussionCategory enum."""

    def test_featured_value(self):
        """FEATURED value is correct."""
        assert DiscussionCategory.FEATURED.value == "featured"

    def test_brief_mention_value(self):
        """BRIEF_MENTION value is correct."""
        assert DiscussionCategory.BRIEF_MENTION.value == "brief_mention"

    def test_skip_value(self):
        """SKIP value is correct."""
        assert DiscussionCategory.SKIP.value == "skip"


class TestRepetitionScore:
    """Tests for RepetitionScore enum."""

    def test_values(self):
        """All repetition score values exist."""
        assert RepetitionScore.HIGH.value == "high"
        assert RepetitionScore.MEDIUM.value == "medium"
        assert RepetitionScore.LOW.value == "low"


class TestSimilarityThreshold:
    """Tests for SimilarityThreshold enum."""

    def test_values(self):
        """All similarity threshold values exist."""
        assert SimilarityThreshold.STRICT.value == "strict"
        assert SimilarityThreshold.MODERATE.value == "moderate"
        assert SimilarityThreshold.AGGRESSIVE.value == "aggressive"


class TestPipelineStage:
    """Tests for PipelineStage enum."""

    def test_core_stages_exist(self):
        """All core pipeline stages are defined."""
        core_stages = [
            "EXTRACT_MESSAGES",
            "PREPROCESS_MESSAGES",
            "TRANSLATE_MESSAGES",
            "SEPARATE_DISCUSSIONS",
            "RANK_DISCUSSIONS",
            "GENERATE_CONTENT",
            "ENRICH_WITH_LINKS",
            "TRANSLATE_FINAL_SUMMARY",
        ]

        for stage_name in core_stages:
            assert hasattr(PipelineStage, stage_name)

    def test_consolidation_stages_exist(self):
        """Consolidation stages are defined."""
        consolidation_stages = [
            "SETUP_CONSOLIDATED_DIRECTORIES",
            "CONSOLIDATE_DISCUSSIONS",
            "RANK_CONSOLIDATED_DISCUSSIONS",
            "GENERATE_CONSOLIDATED_NEWSLETTER",
        ]

        for stage_name in consolidation_stages:
            assert hasattr(PipelineStage, stage_name)


class TestStageStatus:
    """Tests for StageStatus enum."""

    def test_values(self):
        """All status values exist."""
        assert StageStatus.IN_PROGRESS.value == "in_progress"
        assert StageStatus.COMPLETED.value == "completed"
        assert StageStatus.FAILED.value == "failed"
        assert StageStatus.SKIPPED.value == "skipped"


class TestProgressEventType:
    """Tests for ProgressEventType enum."""

    def test_workflow_events(self):
        """Workflow lifecycle events exist."""
        assert ProgressEventType.WORKFLOW_STARTED.value == "workflow_started"
        assert ProgressEventType.WORKFLOW_COMPLETED.value == "workflow_completed"

    def test_chat_events(self):
        """Chat processing events exist."""
        assert ProgressEventType.CHAT_STARTED.value == "chat_started"
        assert ProgressEventType.CHAT_COMPLETED.value == "chat_completed"
        assert ProgressEventType.CHAT_FAILED.value == "chat_failed"


class TestHTTPStatusCodes:
    """Tests for HTTP status code constants."""

    def test_status_codes(self):
        """Status code values are correct."""
        assert HTTP_STATUS_OK == 200
        assert HTTP_STATUS_BAD_REQUEST == 400
        assert HTTP_STATUS_NOT_FOUND == 404
        assert HTTP_STATUS_INTERNAL_SERVER_ERROR == 500


class TestTimeoutConstants:
    """Tests for timeout constants."""

    def test_timeout_values_are_positive(self):
        """All timeout values are positive numbers."""
        assert TIMEOUT_HTTP_REQUEST > 0
        assert TIMEOUT_CACHE_OPERATION > 0

    def test_http_timeout_reasonable(self):
        """HTTP timeout is reasonable (not too short or long)."""
        assert 5 <= TIMEOUT_HTTP_REQUEST <= 120

    def test_cache_timeout_reasonable(self):
        """Cache operation timeout is reasonable."""
        assert 1 <= TIMEOUT_CACHE_OPERATION <= 30


class TestCommunityStructure:
    """Tests for community structure constants."""

    def test_langtalks_community_exists(self):
        """LangTalks community is defined."""
        assert "langtalks" in COMMUNITY_STRUCTURE
        assert "langtalks" in KNOWN_WHATSAPP_CHAT_NAMES

    def test_mcp_israel_community_exists(self):
        """MCP Israel community is defined."""
        assert "mcp_israel" in COMMUNITY_STRUCTURE
        assert "mcp_israel" in KNOWN_WHATSAPP_CHAT_NAMES

    def test_known_chat_names_flattened(self):
        """KNOWN_WHATSAPP_CHAT_NAMES contains flattened chat lists."""
        for community, chats in KNOWN_WHATSAPP_CHAT_NAMES.items():
            assert isinstance(chats, list)
            assert len(chats) > 0


class TestRouteConstants:
    """Tests for route constants."""

    def test_api_prefix(self):
        """API prefix is correct."""
        assert API_V1_PREFIX == "/api"

    def test_newsletter_route(self):
        """Newsletter route is defined."""
        assert ROUTE_GENERATE_PERIODIC_NEWSLETTER == "/generate_periodic_newsletter"
