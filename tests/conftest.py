"""
Pytest configuration and fixtures for the langrag test suite.

This file provides:
1. Python path setup for imports
2. Shared fixtures for common test data
3. Factory functions for creating test objects
4. Mock fixtures for external services (LLM, Beeper, etc.)
"""

import sys
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Any
import pytest

# Ensure src directory is in the Python path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

class MessageFactory:
    """Factory for creating test message objects."""

    _counter = 1000

    @classmethod
    def reset_counter(cls):
        cls._counter = 1000

    @classmethod
    def create_raw_message(
        cls,
        sender: str = "@user1:beeper.com",
        body: str = "Test message content",
        timestamp: int | None = None,
        event_id: str | None = None,
        reply_to: str | None = None
    ) -> dict[str, Any]:
        """Create a raw Matrix/Beeper message."""
        if event_id is None:
            event_id = f"$event_{cls._counter}"
            cls._counter += 1

        if timestamp is None:
            timestamp = 1699999999000 + cls._counter

        content = {"body": body, "msgtype": "m.text"}
        if reply_to:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

        return {
            "event_id": event_id,
            "origin_server_ts": timestamp,
            "sender": sender,
            "content": content,
            "type": "m.room.message",
            "room_id": "!test_room:beeper.com"
        }

    @classmethod
    def create_parsed_message(
        cls,
        sender_id: str = "user_1",
        content: str = "Parsed message content",
        timestamp: int | None = None,
        msg_id: str | None = None,
        replies_to: str | None = None
    ) -> dict[str, Any]:
        """Create a parsed/standardized message."""
        if msg_id is None:
            msg_id = str(cls._counter)
            cls._counter += 1

        if timestamp is None:
            timestamp = 1699999999000 + int(msg_id)

        return {
            "id": msg_id,
            "timestamp": timestamp,
            "sender_id": sender_id,
            "content": content,
            "replies_to": replies_to
        }

    @classmethod
    def create_message_batch(
        cls,
        count: int = 5,
        senders: list[str] = None
    ) -> list[dict[str, Any]]:
        """Create a batch of parsed messages."""
        if senders is None:
            senders = ["user_1", "user_2", "user_3"]

        messages = []
        for i in range(count):
            sender = senders[i % len(senders)]
            messages.append(cls.create_parsed_message(
                sender_id=sender,
                content=f"Message {i + 1} content",
                msg_id=str(1000 + i)
            ))
        return messages


class DiscussionFactory:
    """Factory for creating test discussion objects."""

    _counter = 1

    @classmethod
    def reset_counter(cls):
        cls._counter = 1

    @classmethod
    def create_discussion(
        cls,
        title: str = "Test Discussion",
        nutshell: str = "Summary of the discussion",
        messages: list[dict] | None = None,
        num_messages: int | None = None,
        chat_name: str = "Test Chat",
        disc_id: str | None = None
    ) -> dict[str, Any]:
        """Create a discussion object."""
        if disc_id is None:
            disc_id = f"disc_{cls._counter}"
            cls._counter += 1

        if messages is None:
            messages = MessageFactory.create_message_batch(count=num_messages or 5)

        return {
            "id": disc_id,
            "title": title,
            "nutshell": nutshell,
            "messages": messages,
            "num_messages": len(messages),
            "num_unique_participants": len(set(m["sender_id"] for m in messages)),
            "first_message_in_discussion_timestamp": messages[0]["timestamp"] if messages else 1699999999000,
            "last_message_timestamp": messages[-1]["timestamp"] if messages else 1699999999100,
            "source_chat": chat_name
        }

    @classmethod
    def create_discussion_batch(
        cls,
        count: int = 3,
        chat_name: str = "Test Chat"
    ) -> list[dict[str, Any]]:
        """Create a batch of discussions."""
        discussions = []
        for i in range(count):
            discussions.append(cls.create_discussion(
                title=f"Discussion {i + 1}",
                nutshell=f"Summary of discussion {i + 1}",
                messages=MessageFactory.create_message_batch(count=3 + i),
                chat_name=chat_name
            ))
        return discussions


class RankingFactory:
    """Factory for creating test ranking results."""

    @classmethod
    def create_ranked_discussion(
        cls,
        disc_id: str = "disc_1",
        rank: int = 1,
        title: str = "Ranked Discussion",
        relevance_score: float = 8.5,
        category: str = "featured",
        skip_reason: str | None = None
    ) -> dict[str, Any]:
        """Create a ranked discussion entry."""
        return {
            "discussion_id": disc_id,
            "rank": rank,
            "title": title,
            "ranking_of_relevance_to_gen_ai_engineering": relevance_score,
            "category": category,
            "skip_reason": skip_reason,
            "one_liner_summary": f"Brief summary of {title}",
            "rationale": f"Ranked #{rank} because it covers important topic"
        }

    @classmethod
    def create_ranking_result(
        cls,
        discussions: list[dict[str, Any]] = None,
        top_k: int = 5
    ) -> dict[str, Any]:
        """Create a full ranking result object."""
        if discussions is None:
            discussions = [
                cls.create_ranked_discussion(disc_id=f"disc_{i}", rank=i, title=f"Discussion {i}")
                for i in range(1, 8)
            ]

        featured_ids = [d["discussion_id"] for d in discussions if d["rank"] <= top_k]
        brief_mention = [
            {"discussion_id": d["discussion_id"], "title": d["title"], "one_liner": d["one_liner_summary"]}
            for d in discussions if d["rank"] > top_k and not d.get("skip_reason")
        ]

        return {
            "ranked_discussions": discussions,
            "featured_discussion_ids": featured_ids,
            "brief_mention_items": brief_mention,
            "top_k_applied": top_k,
            "editorial_notes": "Test ranking analysis",
            "topic_diversity": "Good topic coverage"
        }


class NewsletterFactory:
    """Factory for creating test newsletter content."""

    @classmethod
    def create_bullet_point(
        cls,
        label: str = "Key Point",
        content: str = "Important content here"
    ) -> dict[str, str]:
        """Create a newsletter bullet point."""
        return {"label": label, "content": content}

    @classmethod
    def create_summarized_discussion(
        cls,
        title: str = "Featured Discussion",
        bullet_points: list[dict] | None = None,
        timestamp: int = 1699999999000,
        chat_name: str = "Test Chat"
    ) -> dict[str, Any]:
        """Create a summarized discussion for newsletter."""
        if bullet_points is None:
            bullet_points = [
                cls.create_bullet_point("Point 1", "First important point"),
                cls.create_bullet_point("Point 2", "Second important point")
            ]

        return {
            "title": title,
            "bullet_points": bullet_points,
            "first_message_timestamp": timestamp,
            "last_message_timestamp": timestamp + 100000,
            "ranking_of_relevance_to_gen_ai_engineering": 8,
            "number_of_messages": 25,
            "number_of_unique_participants": 10,
            "chat_name": chat_name
        }

    @classmethod
    def create_newsletter_response(
        cls,
        primary_title: str = "Primary Discussion",
        secondary_count: int = 2,
        worth_mentioning: list[str] | None = None
    ) -> dict[str, Any]:
        """Create a full newsletter response object."""
        secondary = [
            cls.create_summarized_discussion(title=f"Secondary {i + 1}")
            for i in range(secondary_count)
        ]

        if worth_mentioning is None:
            worth_mentioning = ["Item 1 to mention", "Item 2 to mention"]

        return {
            "primary_discussion": cls.create_summarized_discussion(title=primary_title),
            "secondary_discussions": secondary,
            "worth_mentioning": worth_mentioning
        }


# ============================================================================
# PYTEST FIXTURES - Data
# ============================================================================

@pytest.fixture
def sample_raw_messages():
    """Fixture providing sample raw Matrix/Beeper messages."""
    MessageFactory.reset_counter()
    return [
        MessageFactory.create_raw_message(sender="@alice:beeper.com", body="Hello everyone!"),
        MessageFactory.create_raw_message(sender="@bob:beeper.com", body="Hi Alice!"),
        MessageFactory.create_raw_message(
            sender="@charlie:beeper.com",
            body="Great discussion!",
            reply_to="$event_1000"
        ),
    ]


@pytest.fixture
def sample_parsed_messages():
    """Fixture providing sample parsed messages."""
    MessageFactory.reset_counter()
    return MessageFactory.create_message_batch(count=10)


@pytest.fixture
def sample_discussions():
    """Fixture providing sample discussions."""
    DiscussionFactory.reset_counter()
    return DiscussionFactory.create_discussion_batch(count=5)


@pytest.fixture
def sample_ranking_result():
    """Fixture providing sample ranking result."""
    return RankingFactory.create_ranking_result()


@pytest.fixture
def sample_newsletter_response():
    """Fixture providing sample newsletter response."""
    return NewsletterFactory.create_newsletter_response()


# ============================================================================
# PYTEST FIXTURES - Temporary Files/Directories
# ============================================================================

@pytest.fixture
def temp_output_dir():
    """Fixture providing a temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_discussions_file(temp_output_dir, sample_discussions):
    """Fixture providing a temporary discussions JSON file."""
    file_path = os.path.join(temp_output_dir, "discussions.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({"discussions": sample_discussions}, f, ensure_ascii=False)
    return file_path


@pytest.fixture
def temp_messages_file(temp_output_dir, sample_parsed_messages):
    """Fixture providing a temporary messages JSON file."""
    file_path = os.path.join(temp_output_dir, "messages.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(sample_parsed_messages, f, ensure_ascii=False)
    return file_path


@pytest.fixture
def temp_ranking_file(temp_output_dir, sample_ranking_result):
    """Fixture providing a temporary ranking results JSON file."""
    file_path = os.path.join(temp_output_dir, "ranking.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(sample_ranking_result, f, ensure_ascii=False)
    return file_path


# ============================================================================
# PYTEST FIXTURES - Mocks
# ============================================================================

@pytest.fixture
def mock_openai_response():
    """Fixture providing a mock OpenAI response."""
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "ranked_discussions": [
            {
                "discussion_id": "disc_1",
                "rank": 1,
                "rationale": "Most relevant discussion"
            }
        ],
        "editorial_notes": "Good content",
        "topic_diversity": "Diverse topics"
    })
    return mock_response


@pytest.fixture
def mock_chat_openai(mock_openai_response):
    """Fixture providing a mocked ChatOpenAI client."""
    with patch('langchain_openai.ChatOpenAI') as mock_class:
        mock_instance = MagicMock()
        mock_instance.__or__ = MagicMock(return_value=MagicMock(invoke=MagicMock(return_value=mock_openai_response)))
        mock_class.return_value = mock_instance
        yield mock_class


@pytest.fixture
def mock_beeper_extractor():
    """Fixture providing a mocked Beeper extractor."""
    mock = MagicMock()
    mock.extract_messages.return_value = "/path/to/extracted.json"
    return mock


@pytest.fixture
def mock_preprocessor():
    """Fixture providing a mocked preprocessor."""
    mock = MagicMock()
    mock.preprocess_data.return_value = "/path/to/preprocessed.json"
    return mock


@pytest.fixture
def mock_content_generator():
    """Fixture providing a mocked content generator."""
    mock = MagicMock()
    mock.generate_content.return_value = {
        "newsletter_summary_path": "/path/to/newsletter.json",
        "markdown_path": "/path/to/newsletter.md",
        "html_path": "/path/to/newsletter.html"
    }
    return mock


# ============================================================================
# PYTEST FIXTURES - FastAPI Test Client
# ============================================================================

@pytest.fixture
def api_client():
    """Fixture providing a FastAPI test client."""
    try:
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    except ImportError:
        pytest.skip("FastAPI test client not available")


# ============================================================================
# PYTEST FIXTURES - Environment
# ============================================================================

@pytest.fixture
def mock_env_vars():
    """Fixture that sets up mock environment variables."""
    env_vars = {
        "BEEPER_ACCESS_TOKEN": "test_token",
        "OPENAI_API_KEY": "test_openai_key",
        "DECRYPTED_KEYS_FILE_PATH": "/fake/path/keys.json"
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def assert_file_exists(file_path: str, message: str = None):
    """Assert that a file exists."""
    assert os.path.exists(file_path), message or f"File not found: {file_path}"


def assert_json_file_valid(file_path: str):
    """Assert that a file is valid JSON."""
    assert_file_exists(file_path)
    with open(file_path, encoding='utf-8') as f:
        try:
            json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in {file_path}: {e}")


def assert_dict_has_keys(d: dict, keys: list[str], message: str = None):
    """Assert that a dictionary has all specified keys."""
    missing = [k for k in keys if k not in d]
    assert not missing, message or f"Missing keys: {missing}"
