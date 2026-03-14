"""
Unit tests for BaseEmailSender.

Test Coverage:
- Validation logic (API key, sender email)
- HTML conversion
- publish_newsletter method
"""

import pytest


class TestBaseEmailSenderValidation:
    """Test BaseEmailSender validation logic."""

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises ValueError."""
        from core.delivery.base import BaseEmailSender

        # Create a concrete subclass for testing
        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        from custom_types.exceptions import ValidationError
        with pytest.raises(ValidationError, match="API key is required"):
            TestSender(api_key=None, sender_email_address="test@example.com")

    def test_empty_api_key_raises_error(self):
        """Test that empty API key raises ValueError."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        from custom_types.exceptions import ValidationError
        with pytest.raises(ValidationError, match="API key is required"):
            TestSender(api_key="", sender_email_address="test@example.com")

    def test_missing_sender_email_raises_error(self):
        """Test that missing sender email raises ValueError."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        from custom_types.exceptions import ValidationError
        with pytest.raises(ValidationError, match="Sender email address is required"):
            TestSender(api_key="test_key", sender_email_address=None)

    def test_valid_initialization(self):
        """Test that valid parameters create instance successfully."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        assert sender.api_key == "test_key"
        assert sender.sender_email_address == "test@example.com"


class TestBaseEmailSenderHtmlConversion:
    """Test BaseEmailSender HTML conversion."""

    def test_convert_to_html_basic_structure(self):
        """Test that HTML conversion creates basic structure."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        content = {
            "group_name": "Test Group",
            "discussions": []
        }

        html, error = sender._convert_to_html(content)

        assert error is None
        assert "Test Group" in html
        assert 'dir="rtl"' in html
        assert "</h1>" in html

    def test_convert_to_html_with_discussions(self):
        """Test HTML conversion with discussions."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        content = {
            "group_name": "Test Group",
            "discussions": [
                {
                    "title": "Discussion Title",
                    "detailed_summary": [
                        {"emoji": "🎯", "point": "First point"},
                        {"emoji": "💡", "point": "Second point"}
                    ],
                    "relevant_links": [
                        {"title": "Link 1", "link": "https://example.com/1"}
                    ],
                    "metadata": {
                        "messages_n": 10,
                        "participants_n": 5
                    }
                }
            ]
        }

        html, error = sender._convert_to_html(content)

        assert error is None
        assert "Discussion Title" in html
        assert "First point" in html
        assert "Second point" in html
        assert "Link 1" in html
        assert "https://example.com/1" in html
        assert "10" in html  # messages count
        assert "5" in html   # participants count

    def test_convert_to_html_empty_discussions(self):
        """Test HTML conversion with empty discussions list."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                pass

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        content = {
            "discussions": []
        }

        html, error = sender._convert_to_html(content)

        assert error is None
        # Should have default group name
        assert "הקבוצה שלך" in html


class TestBaseEmailSenderPublishNewsletter:
    """Test BaseEmailSender publish_newsletter method."""

    def test_publish_newsletter_success(self):
        """Test successful newsletter publishing."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                return True

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        content = {"group_name": "Test", "discussions": []}
        recipients = ["user@example.com"]

        success, message = sender.publish_newsletter(content, recipients)

        assert success is True
        assert "successfully" in message.lower()

    def test_publish_newsletter_send_failure(self):
        """Test newsletter publishing with send failure."""
        from core.delivery.base import BaseEmailSender

        class TestSender(BaseEmailSender):
            def _send(self, subject, html_content, recipient_emails):
                raise Exception("Network error")

        sender = TestSender(api_key="test_key", sender_email_address="test@example.com")

        content = {"group_name": "Test", "discussions": []}
        recipients = ["user@example.com"]

        success, message = sender.publish_newsletter(content, recipients)

        assert success is False
        assert "Network error" in message
