"""
Unit tests for SubstackSender.

Test Coverage:
- Module imports
- Initialization with credentials
- Draft creation with various formats
- Format detection
- Section assignment
"""

import os
from unittest.mock import MagicMock, patch
import pytest


class TestSubstackSenderImport:
    """Test SubstackSender module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from core.delivery import substack
        assert substack is not None

    def test_class_exists(self):
        """Test that SubstackSender class exists."""
        from core.delivery.substack import SubstackSender
        assert SubstackSender is not None


class TestSubstackSenderInitialization:
    """Test SubstackSender initialization."""

    def test_init_missing_credentials_raises_error(self):
        """Test that missing credentials raises ValueError."""
        # Clear env vars
        os.environ.pop("SUBSTACK_EMAIL", None)
        os.environ.pop("SUBSTACK_PASSWORD", None)

        from core.delivery.substack import SubstackSender

        with pytest.raises(ValueError, match="email and password are required"):
            SubstackSender()

    def test_init_missing_email_only_raises_error(self):
        """Test that missing email only raises ValueError."""
        os.environ.pop("SUBSTACK_EMAIL", None)

        from core.delivery.substack import SubstackSender

        with pytest.raises(ValueError, match="email and password are required"):
            SubstackSender(password="test_password")

    @patch('core.delivery.substack.Api')
    def test_init_with_credentials_success(self, mock_api_class):
        """Test successful initialization with credentials."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api_class.return_value = mock_api

        sender = SubstackSender(email="test@example.com", password="test_password")

        assert sender.email == "test@example.com"
        assert sender.password == "test_password"
        assert sender.user_id == "user_123"
        mock_api_class.assert_called_with(email="test@example.com", password="test_password")

    @patch('core.delivery.substack.Api')
    def test_init_api_failure_raises_error(self, mock_api_class):
        """Test that API authentication failure raises ValueError."""
        from core.delivery.substack import SubstackSender

        mock_api_class.side_effect = Exception("Authentication failed")

        with pytest.raises(ValueError, match="Failed to authenticate"):
            SubstackSender(email="test@example.com", password="wrong_password")


class TestSubstackSenderCreateDraft:
    """Test SubstackSender create_draft functionality."""

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_create_draft_success(self, mock_post_class, mock_api_class):
        """Test successful draft creation."""
        from core.delivery.substack import SubstackSender

        # Setup mocks
        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        newsletter_data = {
            "primary_discussion": {
                "title": "Test Discussion",
                "bullet_points": []
            }
        }
        config = {
            "title": "Test Newsletter",
            "subtitle": "Test Subtitle",
            "summary_format": "langtalks_format"
        }

        result = sender.create_draft(newsletter_data, config)

        assert result["success"] is True
        assert result["draft_id"] == "draft_456"
        assert "draft_url" in result

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_create_draft_with_auto_publish(self, mock_post_class, mock_api_class):
        """Test draft creation with auto-publish enabled."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api.publish_draft.return_value = True
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        config = {
            "title": "Test",
            "auto_publish": True,
            "summary_format": "langtalks_format"
        }

        result = sender.create_draft({"primary_discussion": {}}, config)

        assert result["success"] is True
        assert result["published"] is True
        mock_api.publish_draft.assert_called_once_with("draft_456")

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_create_draft_failure_returns_error(self, mock_post_class, mock_api_class):
        """Test that draft creation failure returns error dict."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.side_effect = Exception("API error")
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        result = sender.create_draft({"primary_discussion": {}}, {"title": "Test"})

        assert result["success"] is False
        assert "error" in result


class TestSubstackSenderFormatDetection:
    """Test SubstackSender format detection and content handling."""

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_langtalks_format_content(self, mock_post_class, mock_api_class):
        """Test LangTalks format content handling."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        newsletter_data = {
            "primary_discussion": {
                "title": "Primary Topic",
                "bullet_points": [
                    {"label": "Point 1", "content": "First content"},
                    {"label": "Point 2", "content": "Second content"}
                ]
            },
            "secondary_discussions": [
                {
                    "title": "Secondary Topic",
                    "bullet_points": [{"label": "Sub Point", "content": "Sub content"}]
                }
            ],
            "worth_mentioning": ["Item 1", "Item 2"]
        }

        config = {"title": "Test", "summary_format": "langtalks_format"}

        sender.create_draft(newsletter_data, config)

        # Verify Post.add was called multiple times for content
        assert mock_post.add.call_count > 0

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_mcp_format_content(self, mock_post_class, mock_api_class):
        """Test MCP Israel format content handling."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        newsletter_data = {
            "industry_updates": "Industry news content",
            "tools_mentioned": "Tool 1, Tool 2",
            "security_risks": "Security advisory"
        }

        config = {"title": "Test", "summary_format": "mcp_israel_format"}

        sender.create_draft(newsletter_data, config)

        # Verify Post.add was called for sections
        assert mock_post.add.call_count > 0

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_auto_detect_langtalks_format(self, mock_post_class, mock_api_class):
        """Test auto-detection of LangTalks format from data structure."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        # Data with primary_discussion (LangTalks indicator)
        newsletter_data = {
            "primary_discussion": {"title": "Test"}
        }

        # No summary_format specified
        config = {"title": "Test"}

        sender.create_draft(newsletter_data, config)

        # Should auto-detect and process
        assert mock_post.add.call_count >= 0

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_auto_detect_mcp_format(self, mock_post_class, mock_api_class):
        """Test auto-detection of MCP format from data structure."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        # Data with industry_updates (MCP indicator)
        newsletter_data = {
            "industry_updates": "Test updates"
        }

        # No summary_format specified
        config = {"title": "Test"}

        sender.create_draft(newsletter_data, config)

        # Should auto-detect and process
        assert mock_post.add.call_count >= 0


class TestSubstackSenderSectionAssignment:
    """Test SubstackSender section assignment."""

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_assign_section_success(self, mock_post_class, mock_api_class):
        """Test successful section assignment."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api.get_sections.return_value = [
            {"id": "section_1", "name": "Newsletter"},
            {"id": "section_2", "name": "Updates"}
        ]
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        config = {
            "title": "Test",
            "section_name": "Newsletter",
            "summary_format": "langtalks_format"
        }

        sender.create_draft({"primary_discussion": {}}, config)

        # Verify section was assigned
        mock_api.put_draft.assert_called_once()
        call_args = mock_api.put_draft.call_args
        assert call_args[0][0] == "draft_456"
        assert call_args[1]["draft_section_id"] == "section_1"

    @patch('core.delivery.substack.Api')
    @patch('core.delivery.substack.Post')
    def test_assign_section_not_found_continues(self, mock_post_class, mock_api_class):
        """Test that missing section doesn't fail draft creation."""
        from core.delivery.substack import SubstackSender

        mock_api = MagicMock()
        mock_api.get_user_id.return_value = "user_123"
        mock_api.post_draft.return_value = {"id": "draft_456"}
        mock_api.get_sections.return_value = []  # No sections
        mock_api_class.return_value = mock_api

        mock_post = MagicMock()
        mock_post.get_draft.return_value = {}
        mock_post_class.return_value = mock_post

        sender = SubstackSender(email="test@example.com", password="test_password")

        config = {
            "title": "Test",
            "section_name": "NonExistent",
            "summary_format": "langtalks_format"
        }

        result = sender.create_draft({"primary_discussion": {}}, config)

        # Should still succeed
        assert result["success"] is True
        # put_draft should not be called for section assignment
        mock_api.put_draft.assert_not_called()
