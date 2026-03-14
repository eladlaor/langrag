"""
Unit tests for persistence policy.
"""

import pytest
import logging
from unittest.mock import patch, MagicMock

from db.persistence_policy import (
    PersistencePolicy,
    handle_persistence_error,
)


class TestPersistencePolicy:
    """Tests for PersistencePolicy enum."""

    def test_policy_values(self):
        """Verify policy values are correct."""
        assert PersistencePolicy.FAIL_HARD.value == "fail_hard"
        assert PersistencePolicy.FAIL_SOFT.value == "fail_soft"


class TestHandlePersistenceError:
    """Tests for handle_persistence_error function."""

    def test_fail_hard_raises_runtime_error(self):
        """FAIL_HARD policy should raise RuntimeError."""
        error = Exception("Database connection failed")

        with pytest.raises(RuntimeError) as exc_info:
            handle_persistence_error(
                error=error,
                operation="store_messages",
                policy=PersistencePolicy.FAIL_HARD,
                context={"chat_name": "test_chat"}
            )

        assert "store_messages" in str(exc_info.value)
        assert "Database connection failed" in str(exc_info.value)

    def test_fail_soft_logs_warning(self, caplog):
        """FAIL_SOFT policy should log warning and not raise."""
        error = Exception("Temporary network issue")

        with caplog.at_level(logging.WARNING):
            # Should not raise
            handle_persistence_error(
                error=error,
                operation="store_discussions",
                policy=PersistencePolicy.FAIL_SOFT,
                context={"discussion_count": 10}
            )

        assert "store_discussions" in caplog.text
        assert "non-critical" in caplog.text.lower()

    def test_fail_hard_logs_error(self, caplog):
        """FAIL_HARD should log error before raising."""
        error = ValueError("Invalid data")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError):
                handle_persistence_error(
                    error=error,
                    operation="store_newsletter",
                    policy=PersistencePolicy.FAIL_HARD
                )

        assert "store_newsletter" in caplog.text

    def test_context_included_in_logs(self, caplog):
        """Context dict should be included in log messages."""
        error = Exception("Test error")
        context = {"chat_name": "LangTalks", "message_count": 100}

        with caplog.at_level(logging.WARNING):
            handle_persistence_error(
                error=error,
                operation="test_op",
                policy=PersistencePolicy.FAIL_SOFT,
                context=context
            )

        # Context should be logged
        assert "chat_name" in caplog.text or "context" in caplog.text

    def test_no_context_works(self, caplog):
        """Function works without context parameter."""
        error = Exception("Simple error")

        with caplog.at_level(logging.WARNING):
            handle_persistence_error(
                error=error,
                operation="simple_op",
                policy=PersistencePolicy.FAIL_SOFT
            )

        assert "simple_op" in caplog.text
