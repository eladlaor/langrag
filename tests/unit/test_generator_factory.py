"""
Unit tests for ContentGeneratorFactory class.

These tests verify the factory pattern implementation for creating
content generators based on data source type and summary format.

Test Coverage:
- Factory creation with valid parameters
- Factory creation with invalid parameters (fail-fast)
- Format listing and info retrieval
- All supported combinations
"""

import pytest


# Check if we can import the generator modules
def _can_import_generators():
    """Check if generator modules can be imported."""
    try:
        from core.generation.generators.factory import ContentGeneratorFactory
        return True
    except ImportError:
        return False


# Skip marker for tests requiring proper environment
requires_env = pytest.mark.skipif(
    not _can_import_generators(),
    reason="Requires proper PYTHONPATH setup"
)


@requires_env
class TestContentGeneratorFactory:
    """Test ContentGeneratorFactory class."""

    def test_create_langtalks_generator_success(self):
        """Test creating a LangTalks format generator."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from core.generation.generators.newsletter_generator import NewsletterContentGenerator
        from constants import DataSources, SummaryFormats

        generator = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT
        )

        assert isinstance(generator, NewsletterContentGenerator)
        assert generator._format.format_name == SummaryFormats.LANGTALKS_FORMAT

    def test_create_mcp_generator_success(self):
        """Test creating an MCP Israel format generator."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from core.generation.generators.newsletter_generator import NewsletterContentGenerator
        from constants import DataSources, SummaryFormats

        generator = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.MCP_ISRAEL_FORMAT
        )

        assert isinstance(generator, NewsletterContentGenerator)
        assert generator._format.format_name == SummaryFormats.MCP_ISRAEL_FORMAT

    def test_create_with_string_values_success(self):
        """Test creating generator with string values instead of enums."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from core.generation.generators.newsletter_generator import NewsletterContentGenerator

        generator = ContentGeneratorFactory.create(
            data_source_type="whatsapp_group_chat_messages",
            summary_format="langtalks_format"
        )

        assert isinstance(generator, NewsletterContentGenerator)

    def test_create_with_invalid_data_source_raises_error(self):
        """Test that invalid data source type raises ValueError."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import SummaryFormats

        with pytest.raises(ValueError, match="Unsupported data source type"):
            ContentGeneratorFactory.create(
                data_source_type="invalid_source",
                summary_format=SummaryFormats.LANGTALKS_FORMAT
            )

    def test_create_with_invalid_summary_format_raises_error(self):
        """Test that invalid summary format raises ValueError."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import DataSources

        with pytest.raises(ValueError, match="not found"):
            ContentGeneratorFactory.create(
                data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
                summary_format="invalid_format"
            )

    def test_create_passes_kwargs_to_generator(self):
        """Test that additional kwargs are passed to generator constructor."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import DataSources, SummaryFormats

        # Create generator with extra kwargs
        generator = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT,
            source_name="test_source",
            chat_name="Test Chat"
        )

        # Verify generator was created (kwargs should not raise errors)
        assert generator is not None


@requires_env
class TestContentGeneratorFactoryFormats:
    """Test the format listing and info methods."""

    def test_list_available_formats_returns_list(self):
        """Test that list_available_formats returns a list of format names."""
        from core.generation.generators.factory import ContentGeneratorFactory

        formats = ContentGeneratorFactory.list_available_formats()

        assert isinstance(formats, list)
        assert len(formats) > 0
        assert "langtalks_format" in formats
        assert "mcp_israel_format" in formats

    def test_get_format_info_langtalks(self):
        """Test getting info for LangTalks format."""
        from core.generation.generators.factory import ContentGeneratorFactory

        info = ContentGeneratorFactory.get_format_info("langtalks_format")

        assert info["format_name"] == "langtalks_format"
        assert "display_name" in info
        assert "language" in info

    def test_get_format_info_mcp(self):
        """Test getting info for MCP Israel format."""
        from core.generation.generators.factory import ContentGeneratorFactory

        info = ContentGeneratorFactory.get_format_info("mcp_israel_format")

        assert info["format_name"] == "mcp_israel_format"
        assert "display_name" in info
        assert "language" in info

    def test_get_format_info_invalid_raises_error(self):
        """Test that getting info for invalid format raises KeyError."""
        from core.generation.generators.factory import ContentGeneratorFactory

        with pytest.raises(KeyError):
            ContentGeneratorFactory.get_format_info("invalid_format")


@requires_env
class TestContentGeneratorFactoryUsage:
    """Test typical factory usage patterns."""

    def test_factory_multiple_creates_different_instances(self):
        """Test that multiple creates return different instances."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import DataSources, SummaryFormats

        gen1 = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT
        )

        gen2 = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT
        )

        assert gen1 is not gen2

    def test_factory_creates_generators_for_different_formats(self):
        """Test that different formats create generators with different format names."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import DataSources, SummaryFormats

        langtalks_gen = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT
        )

        mcp_gen = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.MCP_ISRAEL_FORMAT
        )

        assert langtalks_gen._format.format_name != mcp_gen._format.format_name

    def test_factory_classmethod_usage(self):
        """Test that factory can be used as classmethod without instantiation."""
        from core.generation.generators.factory import ContentGeneratorFactory
        from constants import DataSources, SummaryFormats

        # Should work without creating ContentGeneratorFactory instance
        generator = ContentGeneratorFactory.create(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            summary_format=SummaryFormats.LANGTALKS_FORMAT
        )

        assert generator is not None
