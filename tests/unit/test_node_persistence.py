"""
Unit tests for node persistence helpers.
"""

import pytest
from unittest.mock import AsyncMock

from db.node_persistence import (
    generate_newsletter_id,
    persist_to_mongodb,
    NodePersistence,
)
from db.persistence_policy import PersistencePolicy


class TestGenerateNewsletterId:
    """Tests for newsletter ID generation."""

    def test_basic_generation(self):
        """Generate ID from run_id and chat_name."""
        result = generate_newsletter_id("run_123", "LangTalks Community")

        assert result == "run_123_nl_langtalks_community"

    def test_special_characters_slugified(self):
        """Special characters are converted to underscores."""
        result = generate_newsletter_id("run_456", "MCP Israel #2")

        assert result == "run_456_nl_mcp_israel_2"

    def test_whitespace_handling(self):
        """Whitespace is converted to underscores."""
        result = generate_newsletter_id("run_789", "n8n  israel   main")

        assert result == "run_789_nl_n8n_israel_main"

    def test_lowercase_conversion(self):
        """Chat names are lowercased."""
        result = generate_newsletter_id("RUN_ABC", "UPPERCASE Chat")

        assert "uppercase" in result
        assert "UPPERCASE" not in result


class TestPersistToMongodb:
    """Tests for persist_to_mongodb function."""

    @pytest.mark.asyncio
    async def test_skip_when_no_run_id(self):
        """Skip persistence when run_id is None."""
        mock_func = AsyncMock(return_value="stored")

        result = await persist_to_mongodb(
            operation="test_op",
            persist_func=mock_func,
            run_id=None
        )

        assert result is None
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_persistence(self):
        """Call persist_func when run_id exists."""
        mock_func = AsyncMock(return_value=100)

        result = await persist_to_mongodb(
            operation="store_messages",
            persist_func=mock_func,
            run_id="run_123",
            policy=PersistencePolicy.FAIL_SOFT,
            arg1="value1",
            kwarg1="kwvalue1"
        )

        assert result == 100
        mock_func.assert_called_once_with(arg1="value1", kwarg1="kwvalue1")

    @pytest.mark.asyncio
    async def test_fail_soft_returns_none_on_error(self):
        """FAIL_SOFT returns None on error."""
        mock_func = AsyncMock(side_effect=Exception("DB error"))

        result = await persist_to_mongodb(
            operation="failing_op",
            persist_func=mock_func,
            run_id="run_123",
            policy=PersistencePolicy.FAIL_SOFT
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_fail_hard_raises_on_error(self):
        """FAIL_HARD raises RuntimeError on error."""
        mock_func = AsyncMock(side_effect=Exception("Critical failure"))

        with pytest.raises(RuntimeError, match="Critical failure"):
            await persist_to_mongodb(
                operation="critical_op",
                persist_func=mock_func,
                run_id="run_123",
                policy=PersistencePolicy.FAIL_HARD
            )


class TestNodePersistence:
    """Tests for NodePersistence helper class."""

    def test_initialization_from_state(self):
        """Initialize from graph state dict."""
        state = {
            "mongodb_run_id": "run_abc",
            "chat_name": "Test Chat",
            "data_source_name": "langtalks",
            "start_date": "2025-01-01",
            "end_date": "2025-01-07",
            "summary_format": "langtalks_format",
            "desired_language_for_summary": "hebrew",
        }

        persistence = NodePersistence(state)

        assert persistence.run_id == "run_abc"
        assert persistence.chat_name == "Test Chat"
        assert persistence.is_enabled is True

    def test_disabled_when_no_run_id(self):
        """is_enabled is False when no run_id."""
        state = {"chat_name": "Test"}

        persistence = NodePersistence(state)

        assert persistence.is_enabled is False
        assert persistence.newsletter_id is None

    def test_newsletter_id_property(self):
        """newsletter_id property generates correct ID."""
        state = {
            "mongodb_run_id": "run_xyz",
            "chat_name": "My Chat",
        }

        persistence = NodePersistence(state)

        assert persistence.newsletter_id == "run_xyz_nl_my_chat"

    @pytest.mark.asyncio
    async def test_store_messages_skips_when_disabled(self):
        """store_messages returns None when disabled."""
        state = {"chat_name": "Test"}  # No run_id
        persistence = NodePersistence(state)

        result = await persistence.store_messages([{"text": "hello"}])

        assert result is None
