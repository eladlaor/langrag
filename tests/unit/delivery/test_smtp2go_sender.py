"""
Unit tests for SMTP2GOEmailSender.

Test Coverage:
- Module imports
- Initialization with environment variables
- Send functionality with API payload verification
"""

import os
from unittest.mock import MagicMock, patch
import pytest


class TestSMTP2GOEmailSenderImport:
    """Test SMTP2GOEmailSender module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from core.delivery import smtp2go
        assert smtp2go is not None

    def test_class_exists(self):
        """Test that SMTP2GOEmailSender class exists."""
        from core.delivery.smtp2go import SMTP2GOEmailSender
        assert SMTP2GOEmailSender is not None


class TestSMTP2GOEmailSenderInitialization:
    """Test SMTP2GOEmailSender initialization."""

    @patch.dict(os.environ, {"SMTP2GO_API_KEY": "test_smtp2go_key"})
    def test_init_with_env_key(self):
        """Test initialization with API key from environment."""
        from core.delivery.smtp2go import SMTP2GOEmailSender

        sender = SMTP2GOEmailSender(sender_email_address="sender@example.com")

        assert sender.api_key == "test_smtp2go_key"
        assert sender.sender_email_address == "sender@example.com"
        assert "smtp2go.com" in sender.api_url

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_env_key_raises_error(self):
        """Test that missing SMTP2GO_API_KEY raises error."""
        os.environ.pop("SMTP2GO_API_KEY", None)

        from core.delivery.smtp2go import SMTP2GOEmailSender
        from custom_types.exceptions import ValidationError

        with pytest.raises(ValidationError, match="API key is required"):
            SMTP2GOEmailSender(sender_email_address="sender@example.com")


class TestSMTP2GOEmailSenderSend:
    """Test SMTP2GOEmailSender send functionality."""

    @patch('core.delivery.smtp2go.requests.post')
    @patch.dict(os.environ, {"SMTP2GO_API_KEY": "test_smtp2go_key"})
    def test_send_creates_correct_payload(self, mock_post):
        """Test that _send creates correct API payload."""
        from core.delivery.smtp2go import SMTP2GOEmailSender

        mock_post.return_value = MagicMock(status_code=200)

        sender = SMTP2GOEmailSender(sender_email_address="sender@example.com")

        sender._send(
            subject="Test Subject",
            html_content="<p>Test content</p>",
            recipient_emails=["user@example.com"]
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Verify URL
        assert "smtp2go.com" in call_args[0][0]

        # Verify payload
        payload = call_args[1]["json"]
        assert payload["sender"] == "sender@example.com"
        assert payload["to"] == "user@example.com"
        assert payload["subject"] == "Test Subject"
        assert payload["html_body"] == "<p>Test content</p>"

        # Verify headers
        headers = call_args[1]["headers"]
        assert headers["X-Smtp2go-Api-Key"] == "test_smtp2go_key"

    @patch('core.delivery.smtp2go.requests.post')
    @patch.dict(os.environ, {"SMTP2GO_API_KEY": "test_smtp2go_key"})
    def test_send_raises_exception_on_failure(self, mock_post):
        """Test that _send raises exception on API failure."""
        from core.delivery.smtp2go import SMTP2GOEmailSender

        mock_post.side_effect = Exception("Connection error")

        sender = SMTP2GOEmailSender(sender_email_address="sender@example.com")

        with pytest.raises(Exception, match="Failed to send email"):
            sender._send(
                subject="Test Subject",
                html_content="<p>Test</p>",
                recipient_emails=["user@example.com"]
            )


class TestSMTP2GOFullFlow:
    """Test full flow from content to send."""

    @patch('core.delivery.smtp2go.requests.post')
    @patch.dict(os.environ, {"SMTP2GO_API_KEY": "test_key"})
    def test_smtp2go_publish_newsletter_full_flow(self, mock_post):
        """Test full SMTP2GO newsletter publishing flow."""
        from core.delivery.smtp2go import SMTP2GOEmailSender

        mock_post.return_value = MagicMock(status_code=200)

        sender = SMTP2GOEmailSender(sender_email_address="newsletter@example.com")

        content = {
            "group_name": "Test Community",
            "discussions": [
                {"title": "Discussion 1"}
            ]
        }

        success, message = sender.publish_newsletter(content, ["user@example.com"])

        assert success is True
        mock_post.assert_called_once()
