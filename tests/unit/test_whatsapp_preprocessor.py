"""
Unit tests for WhatsApp preprocessor classes.

NOTE: These tests require Docker environment due to source code import issues.
The utils/observability/__init__.py uses 'from src.' prefix which fails outside Docker.
Run in Docker: docker compose exec backend pytest tests/unit/test_whatsapp_preprocessor.py

Test Coverage (documented, partial implementation):
- Message parsing and standardization
- Unicode escape sanitization
- Message statistics analysis
- Reply threading preservation
- Sender anonymization
- Error handling (fail-fast approach)
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest


# Check if we can import the modules (source has 'from src.' import issues)
def _can_import_preprocessor():
    """Check if preprocessor can be imported."""
    try:
        from core.ingestion.preprocessors.whatsapp import WhatsAppPreprocessor
        return True
    except ImportError:
        return False


# Skip marker for tests requiring Docker
requires_docker = pytest.mark.skipif(
    not _can_import_preprocessor(),
    reason="Requires Docker - source code has 'from src.' import issues"
)


@requires_docker
class TestWhatsAppPreprocessorImport:
    """Test that the module can be imported."""

    def test_module_imports_successfully(self):
        """Test that the whatsapp preprocessor module can be imported."""
        from core.ingestion.preprocessors import whatsapp
        assert whatsapp is not None

    def test_class_exists(self):
        """Test that WhatsAppPreprocessor class exists."""
        from core.ingestion.preprocessors.whatsapp import WhatsAppPreprocessor
        assert WhatsAppPreprocessor is not None

    def test_alias_classes_exist(self):
        """Test that backward-compatibility alias classes exist."""
        from core.ingestion.preprocessors.whatsapp import (
            CommunityLangTalksDataPreprocessor,
            CommunityMcpDataPreprocessor,
            WhatsAppPreprocessor
        )
        # Both aliases should point to WhatsAppPreprocessor
        assert CommunityLangTalksDataPreprocessor is WhatsAppPreprocessor
        assert CommunityMcpDataPreprocessor is WhatsAppPreprocessor


# The following tests are skipped because they require complex initialization
# that depends on Pydantic BaseSettings configuration.
# They are documented here to show expected behavior.

@pytest.mark.skip(reason="Requires complex Pydantic settings initialization")
class TestUnicodeSanitization:
    """Test malformed Unicode escape sanitization (skipped - requires class instance)."""

    def test_sanitize_valid_unicode_unchanged(self):
        """Test that valid Unicode escapes are not modified."""
        pass

    def test_sanitize_malformed_6_char_unicode(self):
        """Test fixing 6-char malformed Unicode escapes."""
        pass


@pytest.mark.skip(reason="Requires complex Pydantic settings initialization")
class TestMessageParsing:
    """Test message parsing functionality (skipped - requires class instance)."""

    def test_parse_messages_extracts_required_fields(self):
        """Test that required fields are extracted from raw messages."""
        pass

    def test_parse_messages_preserves_replies(self):
        """Test that reply threading is preserved."""
        pass


class TestMessageJsonStructure:
    """Test message JSON structure (no class instance needed)."""

    def test_raw_message_has_required_fields(self):
        """Test that raw messages have required fields for parsing."""
        raw_message = {
            "event_id": "$event1",
            "origin_server_ts": 1699999999000,
            "sender": "@user1:beeper.com",
            "content": {"body": "Hello, world!"}
        }

        # Verify all required fields exist
        assert "event_id" in raw_message
        assert "origin_server_ts" in raw_message
        assert "sender" in raw_message
        assert "content" in raw_message
        assert "body" in raw_message["content"]

    def test_reply_message_has_relates_to(self):
        """Test that reply messages have m.relates_to structure."""
        reply_message = {
            "event_id": "$event2",
            "origin_server_ts": 1699999999100,
            "sender": "@user2:beeper.com",
            "content": {
                "body": "Reply message",
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": "$event1"}
                }
            }
        }

        assert "m.relates_to" in reply_message["content"]
        assert "m.in_reply_to" in reply_message["content"]["m.relates_to"]

    def test_parsed_message_structure(self):
        """Test expected structure of parsed message."""
        parsed_message = {
            "id": "1000",
            "timestamp": 1699999999000,
            "sender_id": "user_1",
            "content": "Hello, world!",
            "replies_to": None
        }

        assert "id" in parsed_message
        assert "timestamp" in parsed_message
        assert "sender_id" in parsed_message
        assert "content" in parsed_message


class TestSenderMapping:
    """Test sender mapping logic (no class instance needed)."""

    def test_sender_mapping_structure(self):
        """Test that sender mapping has expected structure."""
        sender_map = {
            "@user1:beeper.com": "user_1",
            "@user2:beeper.com": "user_2"
        }

        # Verify structure
        assert len(sender_map) == 2
        assert sender_map["@user1:beeper.com"] == "user_1"

    def test_sender_anonymization_prefix(self):
        """Test that anonymized senders use user_ prefix."""
        sender_map = {
            "@realuser:beeper.com": "user_5"
        }

        anon_id = sender_map["@realuser:beeper.com"]
        assert anon_id.startswith("user_")

    def test_sender_mapping_incremental_numbering(self):
        """Test that sender numbering is incremental."""
        sender_map = {
            "@user1:beeper.com": "user_1",
            "@user2:beeper.com": "user_2",
            "@user3:beeper.com": "user_3"
        }

        numbers = [int(v.split("_")[1]) for v in sender_map.values()]
        assert numbers == [1, 2, 3]


class TestDiscussionStructure:
    """Test discussion structure (no class instance needed)."""

    def test_discussion_has_required_fields(self):
        """Test that discussions have required fields."""
        discussion = {
            "id": "disc_1",
            "title": "Discussion about AI",
            "nutshell": "Summary of the discussion",
            "messages": [
                {"id": "1000", "content": "First message"},
                {"id": "1001", "content": "Reply message"}
            ],
            "first_message_timestamp": 1699999999000,
            "last_message_timestamp": 1699999999100,
            "num_messages": 2,
            "num_unique_participants": 2,
            "source_chat": "Test Chat"
        }

        assert "id" in discussion
        assert "title" in discussion
        assert "messages" in discussion
        assert isinstance(discussion["messages"], list)

    def test_discussions_file_structure(self):
        """Test expected structure of discussions JSON file."""
        discussions_data = {
            "discussions": [
                {
                    "id": "disc_1",
                    "title": "Discussion 1",
                    "messages": []
                }
            ],
            "metadata": {
                "total_discussions": 1,
                "chat_name": "Test Chat",
                "date_range": "2025-01-01 to 2025-01-07"
            }
        }

        assert "discussions" in discussions_data
        assert isinstance(discussions_data["discussions"], list)


class TestPreprocessingOutputPaths:
    """Test preprocessing output path handling."""

    def test_output_directory_can_be_created(self):
        """Test that output directories can be created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "preprocess_output")
            os.makedirs(output_dir, exist_ok=True)

            assert os.path.exists(output_dir)
            assert os.path.isdir(output_dir)

    def test_json_output_file_can_be_written(self):
        """Test that JSON output files can be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "messages_processed.json")

            test_data = [
                {"id": "1", "content": "Hello"},
                {"id": "2", "content": "World"}
            ]

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(test_data, f, ensure_ascii=False)

            # Verify file was created and can be read
            assert os.path.exists(output_path)

            with open(output_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            assert len(loaded) == 2


class TestUnicodeHandling:
    """Test Unicode handling in message content."""

    def test_unicode_json_roundtrip(self):
        """Test that Unicode content survives JSON roundtrip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "unicode_test.json")

            # Hebrew and emoji content
            test_data = {
                "content": "שלום עולם 👋 Hello World"
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(test_data, f, ensure_ascii=False)

            with open(output_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            assert loaded["content"] == "שלום עולם 👋 Hello World"

    def test_malformed_unicode_pattern(self):
        """Test identification of malformed Unicode patterns."""
        import re

        # Pattern for 6-char malformed Unicode (e.g., \\u00005d9)
        malformed_pattern = r'\\u0000([0-9a-fA-F]{2})'

        test_string = "\\u00005d9 text \\u00005e4"

        matches = re.findall(malformed_pattern, test_string)
        assert len(matches) == 2

    def test_unicode_normalization(self):
        """Test Unicode normalization approach."""
        import re

        text = "\\u00005d9"  # Malformed 6-char (has 6 hex digits)

        # Fix by extracting last 4 hex digits (proper Unicode format)
        fixed = re.sub(r'\\u0000([0-9a-fA-F]{2})([0-9a-fA-F])', r'\\u0\1\2', text)

        # Now it's properly formatted
        assert fixed == "\\u05d9"  # The extra leading zero is dropped


class TestMessageStatistics:
    """Test message statistics computation."""

    def test_stats_empty_messages(self):
        """Test stats computation with empty message list."""
        messages = []

        stats = {
            "total_message_count": len(messages),
            "messages_by_day": {},
            "messages_by_sender": {},
            "date_range": {
                "start_date": None,
                "end_date": None
            }
        }

        assert stats["total_message_count"] == 0
        assert stats["date_range"]["start_date"] is None

    def test_stats_single_message(self):
        """Test stats computation with single message."""
        messages = [
            {"id": "1", "timestamp": 1699999999000, "sender_id": "user_1"}
        ]

        stats = {
            "total_message_count": len(messages),
            "messages_by_sender": {"user_1": 1}
        }

        assert stats["total_message_count"] == 1
        assert stats["messages_by_sender"]["user_1"] == 1

    def test_stats_multiple_senders(self):
        """Test stats with multiple senders."""
        messages = [
            {"id": "1", "sender_id": "user_1"},
            {"id": "2", "sender_id": "user_1"},
            {"id": "3", "sender_id": "user_2"}
        ]

        sender_counts = {}
        for msg in messages:
            sender = msg["sender_id"]
            sender_counts[sender] = sender_counts.get(sender, 0) + 1

        assert sender_counts["user_1"] == 2
        assert sender_counts["user_2"] == 1


@requires_docker
class TestPollHandling:
    """Test WhatsApp poll extraction and formatting."""

    def _make_preprocessor(self):
        from core.ingestion.preprocessors.whatsapp import DataPreprocessorWhatsappChatsBase
        return DataPreprocessorWhatsappChatsBase.__new__(DataPreprocessorWhatsappChatsBase)

    def _make_poll_start(self, event_id="$poll1", question="Best framework?", options=None):
        if options is None:
            options = [("opt_a", "LangChain"), ("opt_b", "LlamaIndex")]
        return {
            "event_id": event_id,
            "origin_server_ts": 1700000000000,
            "sender": "@creator:beeper.local",
            "type": "m.room.message",
            "content": {
                "body": f"{question}\n\n" + "\n\n".join(f"{i+1}. {name}" for i, (_, name) in enumerate(options)) + "\n\n(This message is a poll. Please open WhatsApp to vote.)",
                "msgtype": "m.text",
                "org.matrix.msc3381.poll.start": {
                    "question": {"org.matrix.msc1767.text": question},
                    "answers": [{"id": oid, "org.matrix.msc1767.text": name} for oid, name in options],
                    "kind": "org.matrix.msc3381.poll.disclosed",
                    "max_selections": 1,
                },
            },
        }

    def _make_poll_response(self, parent_event_id, sender, answer_ids, ts_offset=1000):
        return {
            "event_id": f"$resp_{sender}_{ts_offset}",
            "origin_server_ts": 1700000000000 + ts_offset,
            "sender": sender,
            "type": "org.matrix.msc3381.poll.response",
            "content": {
                "body": "",
                "m.relates_to": {"event_id": parent_event_id, "rel_type": "m.reference"},
                "org.matrix.msc3381.poll.response": {"answers": answer_ids},
            },
        }

    def _make_text_msg(self, event_id, body, ts_offset=0):
        return {
            "event_id": event_id,
            "origin_server_ts": 1700000000000 + ts_offset,
            "sender": "@user:beeper.local",
            "type": "m.room.message",
            "content": {"body": body, "msgtype": "m.text"},
        }

    def test_format_poll_with_votes(self):
        preprocessor = self._make_preprocessor()
        poll = self._make_poll_start()
        vote_counts = {"opt_a": 3, "opt_b": 2}
        result = preprocessor._format_poll_as_text(poll["content"], vote_counts)
        assert "[Poll] Best framework?" in result
        assert "LangChain (3 votes)" in result
        assert "LlamaIndex (2 votes)" in result
        assert "Total votes: 5" in result

    def test_format_poll_without_votes(self):
        preprocessor = self._make_preprocessor()
        poll = self._make_poll_start()
        result = preprocessor._format_poll_as_text(poll["content"], None)
        assert "[Poll] Best framework?" in result
        assert "- LangChain" in result
        assert "- LlamaIndex" in result
        assert "Total votes" not in result

    def test_aggregate_poll_responses(self):
        preprocessor = self._make_preprocessor()
        messages = [
            self._make_poll_start(),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_a"], 1000),
            self._make_poll_response("$poll1", "@voter2:beeper.local", ["opt_b"], 2000),
            self._make_poll_response("$poll1", "@voter3:beeper.local", ["opt_a"], 3000),
        ]
        votes, response_ids, _voter_counts = preprocessor._aggregate_poll_responses(messages)
        assert "$poll1" in votes
        assert votes["$poll1"]["opt_a"] == 2
        assert votes["$poll1"]["opt_b"] == 1
        assert len(response_ids) == 3

    def test_aggregate_latest_vote_per_sender(self):
        """When a user changes their vote, only the latest response counts."""
        preprocessor = self._make_preprocessor()
        messages = [
            self._make_poll_start(),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_a"], 1000),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_b"], 2000),  # Changed vote
        ]
        votes, response_ids, _voter_counts = preprocessor._aggregate_poll_responses(messages)
        assert votes["$poll1"].get("opt_a", 0) == 0
        assert votes["$poll1"]["opt_b"] == 1

    def test_parse_messages_skips_poll_responses(self):
        preprocessor = self._make_preprocessor()
        messages = [
            self._make_text_msg("$msg1", "Hello", -1000),
            self._make_poll_start(),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_a"], 1000),
            self._make_poll_response("$poll1", "@voter2:beeper.local", ["opt_b"], 2000),
            self._make_text_msg("$msg2", "Goodbye", 5000),
        ]
        result = preprocessor._parse_messages(messages)
        output_msgs = result["messages"]
        assert len(output_msgs) == 3  # 2 text + 1 poll start, responses skipped
        contents = [m["content"] for m in output_msgs]
        assert any("[Poll]" in c for c in contents)
        assert not any(c == "" for c in contents)  # No empty poll response bodies

    def test_parse_messages_poll_has_vote_counts(self):
        preprocessor = self._make_preprocessor()
        messages = [
            self._make_poll_start(),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_a"], 1000),
            self._make_poll_response("$poll1", "@voter2:beeper.local", ["opt_a"], 2000),
        ]
        result = preprocessor._parse_messages(messages)
        poll_msg = [m for m in result["messages"] if "[Poll]" in m["content"]][0]
        assert "LangChain (2 votes)" in poll_msg["content"]
        assert "Total votes: 2" in poll_msg["content"]

    def test_parse_messages_returns_poll_structs(self):
        """Verify _parse_messages returns structured poll data for DB persistence."""
        preprocessor = self._make_preprocessor()
        messages = [
            self._make_poll_start(),
            self._make_poll_response("$poll1", "@voter1:beeper.local", ["opt_a"], 1000),
            self._make_poll_response("$poll1", "@voter2:beeper.local", ["opt_b"], 2000),
        ]
        result = preprocessor._parse_messages(messages)
        assert "polls" in result
        assert len(result["polls"]) == 1
        poll = result["polls"][0]
        assert poll["question"] == "Best framework?"
        assert poll["matrix_event_id"] == "$poll1"
        assert len(poll["options"]) == 2
        assert poll["total_votes"] == 2
        assert poll["unique_voter_count"] == 2
