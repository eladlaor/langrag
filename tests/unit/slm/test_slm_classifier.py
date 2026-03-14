"""
Unit tests for SLM Message Classifier.

Tests cover:
- Message classification logic
- Response parsing
- Batch classification
- Filter statistics
- Helper functions
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_types.slm_schemas import (
    MessageClassification,
    MessageClassificationResult,
    MessageForClassification,
    BatchClassificationResult,
    SLMFilterStats,
)


class TestMessageClassificationResult:
    """Test MessageClassificationResult schema."""

    def test_result_with_keep_classification(self):
        """Test result with KEEP classification."""
        result = MessageClassificationResult(
            classification=MessageClassification.KEEP,
            reason="technical discussion",
            confidence=0.9,
            message_id="msg_123",
        )

        assert result.classification == MessageClassification.KEEP
        assert result.reason == "technical discussion"
        assert result.confidence == 0.9
        assert result.message_id == "msg_123"

    def test_result_with_filter_classification(self):
        """Test result with FILTER classification."""
        result = MessageClassificationResult(
            classification=MessageClassification.FILTER,
            reason="greeting only",
            confidence=0.85,
        )

        assert result.classification == MessageClassification.FILTER
        assert result.reason == "greeting only"

    def test_result_defaults(self):
        """Test result default values."""
        result = MessageClassificationResult(
            classification=MessageClassification.UNCERTAIN,
        )

        assert result.reason == ""
        assert result.confidence == 1.0
        assert result.message_id is None


class TestMessageForClassification:
    """Test MessageForClassification schema."""

    def test_message_with_all_fields(self):
        """Test message with all fields populated."""
        msg = MessageForClassification(
            message_id="msg_123",
            text="How do I use LangChain agents?",
            sender_name="John",
            previous_message_summary="Discussion about LLM frameworks",
        )

        assert msg.message_id == "msg_123"
        assert msg.text == "How do I use LangChain agents?"
        assert msg.sender_name == "John"
        assert msg.previous_message_summary == "Discussion about LLM frameworks"

    def test_message_with_required_only(self):
        """Test message with only required fields."""
        msg = MessageForClassification(
            message_id="msg_456",
            text="Good morning!",
        )

        assert msg.message_id == "msg_456"
        assert msg.text == "Good morning!"
        assert msg.sender_name is None
        assert msg.previous_message_summary is None


class TestBatchClassificationResult:
    """Test BatchClassificationResult schema."""

    def test_batch_result_empty(self):
        """Test empty batch result."""
        result = BatchClassificationResult()

        assert result.results == []
        assert result.total_messages == 0
        assert result.kept_count == 0
        assert result.filtered_count == 0
        assert result.uncertain_count == 0
        assert result.slm_available is True

    def test_batch_result_with_counts(self):
        """Test batch result with classification counts."""
        result = BatchClassificationResult(
            total_messages=10,
            kept_count=5,
            filtered_count=3,
            uncertain_count=2,
            processing_time_ms=500.0,
        )

        assert result.total_messages == 10
        assert result.kept_count == 5
        assert result.filtered_count == 3
        assert result.uncertain_count == 2
        assert result.processing_time_ms == 500.0


class TestSLMFilterStats:
    """Test SLMFilterStats schema."""

    def test_filter_stats_defaults(self):
        """Test filter stats default values."""
        stats = SLMFilterStats()

        assert stats.enabled is False
        assert stats.total_input_messages == 0
        assert stats.total_output_messages == 0
        assert stats.filter_rate == 0.0
        assert stats.fallback_used is False

    def test_calculate_filter_rate(self):
        """Test filter rate calculation."""
        stats = SLMFilterStats(
            enabled=True,
            total_input_messages=100,
            total_output_messages=80,
            kept=60,
            filtered=20,
            uncertain=20,
        )

        rate = stats.calculate_filter_rate()

        assert rate == 20.0  # 20% filtered
        assert stats.filter_rate == 20.0

    def test_calculate_filter_rate_zero_input(self):
        """Test filter rate calculation with zero input messages."""
        stats = SLMFilterStats(enabled=True)
        rate = stats.calculate_filter_rate()

        assert rate == 0.0


class TestMessageClassifierResponseParsing:
    """Test MessageClassifier response parsing logic."""

    def test_parse_keep_response(self):
        """Test parsing KEEP classification response."""
        with patch("core.slm.classifier.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.confidence_threshold = 0.7
            mock_slm.batch_size = 10
            mock_settings.return_value.slm = mock_slm

            from core.slm.classifier import MessageClassifier

            classifier = MessageClassifier(provider=MagicMock())
            result = classifier._parse_response(
                "KEEP - technical question about LangChain",
                "msg_123"
            )

            assert result.classification == MessageClassification.KEEP
            assert "technical question" in result.reason.lower()
            assert result.message_id == "msg_123"

    def test_parse_filter_response(self):
        """Test parsing FILTER classification response."""
        with patch("core.slm.classifier.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.confidence_threshold = 0.7
            mock_slm.batch_size = 10
            mock_settings.return_value.slm = mock_slm

            from core.slm.classifier import MessageClassifier

            classifier = MessageClassifier(provider=MagicMock())
            result = classifier._parse_response(
                "FILTER - greeting only message",
                "msg_456"
            )

            assert result.classification == MessageClassification.FILTER
            assert "greeting" in result.reason.lower()

    def test_parse_uncertain_response(self):
        """Test parsing UNCERTAIN classification response."""
        with patch("core.slm.classifier.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.confidence_threshold = 0.7
            mock_slm.batch_size = 10
            mock_settings.return_value.slm = mock_slm

            from core.slm.classifier import MessageClassifier

            classifier = MessageClassifier(provider=MagicMock())
            result = classifier._parse_response(
                "UNCERTAIN - needs context",
                "msg_789"
            )

            assert result.classification == MessageClassification.UNCERTAIN

    def test_parse_malformed_response_defaults_to_uncertain(self):
        """Test parsing malformed response defaults to UNCERTAIN (fail-safe)."""
        with patch("core.slm.classifier.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.confidence_threshold = 0.7
            mock_slm.batch_size = 10
            mock_settings.return_value.slm = mock_slm

            from core.slm.classifier import MessageClassifier

            classifier = MessageClassifier(provider=MagicMock())
            result = classifier._parse_response(
                "gibberish response",
                "msg_000"
            )

            # Malformed responses should be UNCERTAIN (fail-safe)
            assert result.classification == MessageClassification.UNCERTAIN
            assert "Unparseable" in result.reason

    def test_parse_response_without_separator(self):
        """Test parsing response without ' - ' separator."""
        with patch("core.slm.classifier.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.confidence_threshold = 0.7
            mock_slm.batch_size = 10
            mock_settings.return_value.slm = mock_slm

            from core.slm.classifier import MessageClassifier

            classifier = MessageClassifier(provider=MagicMock())
            result = classifier._parse_response("KEEP", "msg_simple")

            assert result.classification == MessageClassification.KEEP
            assert result.reason == ""


class TestConvertRawMessages:
    """Test convert_raw_messages_to_classification_input helper."""

    def test_convert_messages_basic(self):
        """Test converting basic raw messages."""
        from core.slm.classifier import convert_raw_messages_to_classification_input

        raw_messages = [
            {"id": "msg_1", "content": "Hello world", "sender_name": "Alice"},
            {"id": "msg_2", "content": "How are you?", "sender_name": "Bob"},
        ]

        result = convert_raw_messages_to_classification_input(raw_messages)

        assert len(result) == 2
        assert result[0].message_id == "msg_1"
        assert result[0].text == "Hello world"
        assert result[0].sender_name == "Alice"
        assert result[1].message_id == "msg_2"

    def test_convert_messages_with_context(self):
        """Test converting messages includes previous message context."""
        from core.slm.classifier import convert_raw_messages_to_classification_input

        raw_messages = [
            {"id": "msg_1", "content": "First message"},
            {"id": "msg_2", "content": "Second message"},
        ]

        result = convert_raw_messages_to_classification_input(
            raw_messages,
            include_context=True
        )

        # Second message should have context from first
        assert result[1].previous_message_summary == "First message"

    def test_convert_messages_without_context(self):
        """Test converting messages without context."""
        from core.slm.classifier import convert_raw_messages_to_classification_input

        raw_messages = [
            {"id": "msg_1", "content": "First message"},
            {"id": "msg_2", "content": "Second message"},
        ]

        result = convert_raw_messages_to_classification_input(
            raw_messages,
            include_context=False
        )

        assert result[1].previous_message_summary is None

    def test_convert_messages_alternative_field_names(self):
        """Test converting messages with alternative field names."""
        from core.slm.classifier import convert_raw_messages_to_classification_input

        raw_messages = [
            {"event_id": "evt_1", "body": "Message body", "author": "Charlie"},
            {"message_id": "mid_2", "text": "Another message", "display_name": "Dave"},
        ]

        result = convert_raw_messages_to_classification_input(raw_messages)

        assert result[0].message_id == "evt_1"
        assert result[0].text == "Message body"
        assert result[1].message_id == "mid_2"
        assert result[1].text == "Another message"


class TestFilterMessagesByClassification:
    """Test filter_messages_by_classification helper."""

    def test_filter_keeps_keep_and_uncertain(self):
        """Test filter keeps KEEP and UNCERTAIN messages."""
        from core.slm.classifier import filter_messages_by_classification

        messages = [
            {"id": "msg_1", "content": "Technical discussion"},
            {"id": "msg_2", "content": "Good morning"},
            {"id": "msg_3", "content": "Ambiguous message"},
        ]

        classification_results = BatchClassificationResult(
            results=[
                MessageClassificationResult(
                    classification=MessageClassification.KEEP,
                    message_id="msg_1"
                ),
                MessageClassificationResult(
                    classification=MessageClassification.FILTER,
                    message_id="msg_2"
                ),
                MessageClassificationResult(
                    classification=MessageClassification.UNCERTAIN,
                    message_id="msg_3"
                ),
            ],
            slm_available=True,
        )

        filtered, stats = filter_messages_by_classification(
            messages,
            classification_results
        )

        # Should keep msg_1 (KEEP) and msg_3 (UNCERTAIN), filter msg_2
        assert len(filtered) == 2
        assert any(m["id"] == "msg_1" for m in filtered)
        assert any(m["id"] == "msg_3" for m in filtered)
        assert not any(m["id"] == "msg_2" for m in filtered)

        assert stats.kept == 1
        assert stats.filtered == 1
        assert stats.uncertain == 1

    def test_filter_keeps_all_when_no_results(self):
        """Test filter keeps all messages when no classification results (fail-safe)."""
        from core.slm.classifier import filter_messages_by_classification

        messages = [
            {"id": "msg_1", "content": "Message 1"},
            {"id": "msg_2", "content": "Message 2"},
        ]

        classification_results = BatchClassificationResult(
            results=[],  # No results
            slm_available=False,
        )

        filtered, stats = filter_messages_by_classification(
            messages,
            classification_results
        )

        # Should keep all messages (fail-safe)
        assert len(filtered) == 2
        assert stats.fallback_used is True

    def test_filter_calculates_stats_correctly(self):
        """Test filter calculates statistics correctly."""
        from core.slm.classifier import filter_messages_by_classification

        messages = [
            {"id": f"msg_{i}", "content": f"Message {i}"}
            for i in range(10)
        ]

        classification_results = BatchClassificationResult(
            results=[
                MessageClassificationResult(
                    classification=MessageClassification.KEEP,
                    message_id=f"msg_{i}"
                )
                for i in range(5)
            ] + [
                MessageClassificationResult(
                    classification=MessageClassification.FILTER,
                    message_id=f"msg_{i}"
                )
                for i in range(5, 8)
            ] + [
                MessageClassificationResult(
                    classification=MessageClassification.UNCERTAIN,
                    message_id=f"msg_{i}"
                )
                for i in range(8, 10)
            ],
            slm_available=True,
        )

        filtered, stats = filter_messages_by_classification(
            messages,
            classification_results
        )

        assert stats.total_input_messages == 10
        assert stats.total_output_messages == 7  # 5 KEEP + 2 UNCERTAIN
        assert stats.kept == 5
        assert stats.filtered == 3
        assert stats.uncertain == 2
        assert stats.filter_rate == 30.0  # 3/10 = 30%
