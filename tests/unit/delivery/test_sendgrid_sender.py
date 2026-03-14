"""
Unit tests for SendGridEmailSender.

Test Coverage:
- Module imports
- Initialization with environment variables
- Send functionality
"""

import os
from unittest.mock import MagicMock, patch
import pytest


class TestSendGridEmailSenderImport:
    """Test SendGridEmailSender module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from core.delivery import sendgrid
        assert sendgrid is not None

    def test_class_exists(self):
        """Test that SendGridEmailSender class exists."""
        from core.delivery.sendgrid import SendGridEmailSender
        assert SendGridEmailSender is not None


class TestSendGridEmailSenderInitialization:
    """Test SendGridEmailSender initialization."""

    @patch.dict(os.environ, {"SENDGRID_API_KEY": "test_sendgrid_key"})
    def test_init_with_env_key(self):
        """Test initialization with API key from environment."""
        from core.delivery.sendgrid import SendGridEmailSender

        sender = SendGridEmailSender(sender_email_address="sender@example.com")

        assert sender.api_key == "test_sendgrid_key"
        assert sender.sender_email_address == "sender@example.com"

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_env_key_raises_error(self):
        """Test that missing SENDGRID_API_KEY raises error."""
        # Need to clear any cached env value
        os.environ.pop("SENDGRID_API_KEY", None)

        from core.delivery.sendgrid import SendGridEmailSender
        from custom_types.exceptions import ValidationError

        with pytest.raises(ValidationError, match="API key is required"):
            SendGridEmailSender(sender_email_address="sender@example.com")


class TestSendGridEmailSenderSend:
    """Test SendGridEmailSender send functionality."""

    @patch('core.delivery.sendgrid.SendGridAPIClient')
    @patch.dict(os.environ, {"SENDGRID_API_KEY": "test_sendgrid_key"})
    def test_send_creates_correct_message(self, mock_client_class):
        """Test that _send creates correct Mail object."""
        from core.delivery.sendgrid import SendGridEmailSender

        mock_client = MagicMock()
        mock_client.send.return_value = MagicMock(status_code=202, body="")
        mock_client_class.return_value = mock_client

        sender = SendGridEmailSender(sender_email_address="sender@example.com")

        sender._send(
            subject="Test Subject",
            html_content="<p>Test content</p>",
            recipient_emails=["user@example.com"]
        )

        # Verify SendGridAPIClient was called with API key
        mock_client_class.assert_called_with("test_sendgrid_key")
        # Verify send was called
        mock_client.send.assert_called_once()

    @patch('core.delivery.sendgrid.SendGridAPIClient')
    @patch.dict(os.environ, {"SENDGRID_API_KEY": "test_sendgrid_key"})
    def test_send_raises_exception_on_failure(self, mock_client_class):
        """Test that _send raises exception on SendGrid failure."""
        from core.delivery.sendgrid import SendGridEmailSender

        mock_client = MagicMock()
        mock_client.send.side_effect = Exception("SendGrid API error")
        mock_client_class.return_value = mock_client

        sender = SendGridEmailSender(sender_email_address="sender@example.com")

        with pytest.raises(Exception, match="Failed to send email"):
            sender._send(
                subject="Test Subject",
                html_content="<p>Test</p>",
                recipient_emails=["user@example.com"]
            )


class TestSendGridFullFlow:
    """Test full flow from content to send."""

    @patch('core.delivery.sendgrid.SendGridAPIClient')
    @patch.dict(os.environ, {"SENDGRID_API_KEY": "test_key"})
    def test_sendgrid_publish_newsletter_full_flow(self, mock_client_class):
        """Test full SendGrid newsletter publishing flow."""
        from core.delivery.sendgrid import SendGridEmailSender

        mock_client = MagicMock()
        mock_client.send.return_value = MagicMock(status_code=202)
        mock_client_class.return_value = mock_client

        sender = SendGridEmailSender(sender_email_address="newsletter@example.com")

        content = {
            "group_name": "Test Community",
            "discussions": [
                {
                    "title": "AI Discussion",
                    "detailed_summary": [
                        {"emoji": "🤖", "point": "AI is transforming industries"}
                    ]
                }
            ]
        }

        success, message = sender.publish_newsletter(content, ["user@example.com"])

        assert success is True
        mock_client.send.assert_called_once()
