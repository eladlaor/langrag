"""
Unit tests for LLM utilities (interface, factory, OpenAI provider, prompts).

Test Coverage:
- LLMProviderInterface: abstract methods, structure
- LLMProviderFactory: registration, creation, error handling
- OpenAIProvider: initialization, purpose mapping, input building
- Prompts: structure, placeholders

NOTE: These tests require Docker environment due to source code import issues.
The utils/observability/__init__.py uses 'from src.' prefix which fails outside Docker.
Run in Docker: docker compose exec backend pytest tests/unit/test_llm_utils.py
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# Check if we can import the modules (source has 'from src.' import issues)
def _can_import_llm_utils():
    """Check if llm utils can be imported."""
    try:
        from utils.llm import LLMProviderInterface
        return True
    except ImportError:
        return False


# Skip marker for tests requiring Docker
requires_docker = pytest.mark.skipif(
    not _can_import_llm_utils(),
    reason="Requires Docker - source code has 'from src.' import issues"
)


# ============================================================================
# LLM PROVIDER INTERFACE TESTS
# ============================================================================

@requires_docker
class TestLLMProviderInterfaceImport:
    """Test LLMProviderInterface module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from utils.llm import interface
        assert interface is not None

    def test_class_exists(self):
        """Test that LLMProviderInterface class exists."""
        from utils.llm.interface import LLMProviderInterface
        assert LLMProviderInterface is not None

    def test_interface_is_abstract(self):
        """Test that LLMProviderInterface cannot be instantiated directly."""
        from utils.llm.interface import LLMProviderInterface

        # Should not be directly instantiable due to abstract methods
        with pytest.raises(TypeError):
            LLMProviderInterface()


@requires_docker
class TestLLMProviderInterfaceMethods:
    """Test LLMProviderInterface method definitions."""

    def test_interface_has_call_method(self):
        """Test that interface defines call_with_structured_output_generic method."""
        from utils.llm.interface import LLMProviderInterface

        assert hasattr(LLMProviderInterface, 'call_with_structured_output_generic')

    def test_interface_has_structured_output_method(self):
        """Test that interface defines call_with_structured_output method."""
        from utils.llm.interface import LLMProviderInterface

        assert hasattr(LLMProviderInterface, 'call_with_structured_output')

    def test_interface_has_streaming_method(self):
        """Test that interface defines call_with_json_output method."""
        from utils.llm.interface import LLMProviderInterface

        assert hasattr(LLMProviderInterface, 'call_with_json_output')

    def test_interface_has_get_input_method(self):
        """Test that interface defines call_simple method."""
        from utils.llm.interface import LLMProviderInterface

        assert hasattr(LLMProviderInterface, 'call_simple')


# ============================================================================
# LLM PROVIDER FACTORY TESTS
# ============================================================================

@requires_docker
class TestLLMProviderFactoryImport:
    """Test LLMProviderFactory module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from utils.llm import factory
        assert factory is not None

    def test_class_exists(self):
        """Test that LLMProviderFactory class exists."""
        from utils.llm.factory import LLMProviderFactory
        assert LLMProviderFactory is not None


@requires_docker
class TestLLMProviderFactoryRegistration:
    """Test LLMProviderFactory registration functionality."""

    def test_register_provider(self):
        """Test registering a custom provider."""
        from utils.llm.factory import LLMProviderFactory
        from utils.llm.interface import LLMProviderInterface

        # Create mock provider class
        class MockProvider(LLMProviderInterface):
            def call(self, purpose, **kwargs):
                pass

            def call_with_structured_output(self, purpose, response_schema, **kwargs):
                pass

            def call_with_streaming_response(self, purpose, **kwargs):
                pass

            def _get_input_by_purpose(self, purpose, call_type, **kwargs):
                pass

        # Clear existing providers for clean test
        original_providers = LLMProviderFactory._providers.copy()
        LLMProviderFactory._providers = {}

        try:
            LLMProviderFactory.register("mock", MockProvider)

            assert "mock" in LLMProviderFactory._providers
            assert LLMProviderFactory._providers["mock"] is MockProvider
        finally:
            # Restore original providers
            LLMProviderFactory._providers = original_providers


@requires_docker
class TestLLMProviderFactoryCreate:
    """Test LLMProviderFactory create functionality."""

    def test_create_unknown_provider_raises_error(self):
        """Test that creating unknown provider raises ValueError."""
        from utils.llm.factory import LLMProviderFactory

        with pytest.raises(ValueError, match="not found"):
            LLMProviderFactory.create("nonexistent_provider")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"})
    def test_create_default_openai_provider(self):
        """Test creating default OpenAI provider."""
        from utils.llm.factory import LLMProviderFactory
        from utils.llm.openai_provider import OpenAIProvider

        provider = LLMProviderFactory.create()

        assert isinstance(provider, OpenAIProvider)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"})
    def test_create_openai_provider_explicit(self):
        """Test creating OpenAI provider explicitly."""
        from utils.llm.factory import LLMProviderFactory
        from utils.llm.openai_provider import OpenAIProvider

        provider = LLMProviderFactory.create(provider_name="openai")

        assert isinstance(provider, OpenAIProvider)


# ============================================================================
# OPENAI PROVIDER TESTS
# ============================================================================

@requires_docker
class TestOpenAIProviderImport:
    """Test OpenAIProvider module imports."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        from utils.llm import openai_provider
        assert openai_provider is not None

    def test_class_exists(self):
        """Test that OpenAIProvider class exists."""
        from utils.llm.openai_provider import OpenAIProvider
        assert OpenAIProvider is not None

    def test_backward_compat_alias_exists(self):
        """Test that OpenaiCaller alias exists for backward compatibility."""
        from utils.llm.openai_provider import OpenaiCaller, OpenAIProvider
        assert OpenaiCaller is OpenAIProvider


@requires_docker
class TestOpenAIProviderInitialization:
    """Test OpenAIProvider initialization."""

    def test_init_creates_purpose_map(self):
        """Test that initialization creates INPUT_PURPOSE_MAP."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        assert provider.INPUT_PURPOSE_MAP is not None
        assert "structured_output" in provider.INPUT_PURPOSE_MAP

    def test_init_purpose_map_has_all_purposes(self):
        """Test that purpose map contains all expected purposes."""
        from utils.llm.openai_provider import OpenAIProvider
        from constants import LlmInputPurposes

        provider = OpenAIProvider()

        structured_output_map = provider.INPUT_PURPOSE_MAP["structured_output"]

        # Check all expected purposes
        assert LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES in structured_output_map
        assert LlmInputPurposes.SEPARATE_DISCUSSIONS in structured_output_map
        assert LlmInputPurposes.TRANSLATE_SUMMARY in structured_output_map
        assert LlmInputPurposes.GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER in structured_output_map


@requires_docker
class TestOpenAIProviderGetClient:
    """Test OpenAIProvider client initialization."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test_api_key"})
    @patch('utils.llm.openai_provider.AsyncOpenAI')
    def test_get_client_initializes_once(self, mock_openai_class):
        """Test that OpenAI client is initialized only once."""
        from utils.llm.openai_provider import OpenAIProvider

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        # Call twice
        client1 = provider._get_openai_client()
        client2 = provider._get_openai_client()

        # Should be same instance
        assert client1 is client2
        # AsyncOpenAI class should only be called once
        mock_openai_class.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    def test_get_client_missing_key_raises_error(self):
        """Test that missing API key raises exception."""
        os.environ.pop("OPENAI_API_KEY", None)

        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception, match="OPENAI_API_KEY"):
            provider._get_openai_client()


@requires_docker
class TestOpenAIProviderInputBuilders:
    """Test OpenAIProvider input builder methods."""

    def test_translate_messages_missing_content_raises_error(self):
        """Test that missing content_batch raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_translate_whatsapp_group_messages()

    def test_translate_messages_builds_correct_input(self):
        """Test that translate messages builds correct input structure."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        content_batch = [
            {"id": "1", "content": "Hello"},
            {"id": "2", "content": "World"}
        ]

        result = provider._get_input_for_translate_whatsapp_group_messages(
            content_batch=content_batch,
            translate_from="hebrew",
            translate_to="english"
        )

        assert "model" in result
        assert "messages" in result
        assert "temperature" in result
        assert len(result["messages"]) == 2  # system + user
        assert result["messages"][0]["role"] == "system"
        assert "hebrew" in result["messages"][0]["content"]
        assert "english" in result["messages"][0]["content"]

    def test_separate_discussions_missing_messages_raises_error(self):
        """Test that missing messages raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_separate_whatsapp_group_message_discussions(
                chat_name="Test Chat"
            )

    def test_separate_discussions_missing_chat_name_raises_error(self):
        """Test that missing chat_name raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_separate_whatsapp_group_message_discussions(
                messages=[{"id": "1", "content": "Test"}]
            )

    def test_separate_discussions_builds_correct_input(self):
        """Test that separate discussions builds correct input structure."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        messages = [
            {"id": "1", "content": "First message"},
            {"id": "2", "content": "Second message"}
        ]

        result = provider._get_input_for_separate_whatsapp_group_message_discussions(
            messages=messages,
            chat_name="Test Chat"
        )

        assert "model" in result
        assert "messages" in result
        assert "temperature" in result
        assert len(result["messages"]) == 2  # system + user

    def test_translate_summary_missing_input_raises_error(self):
        """Test that missing input_to_translate raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_translate_newsletter_summary(
                desired_language_for_summary="hebrew"
            )

    def test_translate_summary_builds_correct_input(self):
        """Test that translate summary builds correct input structure."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        result = provider._get_input_for_translate_newsletter_summary(
            input_to_translate="Test newsletter content",
            desired_language_for_summary="hebrew"
        )

        assert "model" in result
        assert "messages" in result
        assert "temperature" in result

    def test_langtalks_newsletter_missing_input_raises_error(self):
        """Test that missing json_input_to_summarize raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_generate_content_wa_community_langtalks_newsletter(
                examples=["Example 1"]
            )

    def test_langtalks_newsletter_missing_examples_raises_error(self):
        """Test that missing examples raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_for_generate_content_wa_community_langtalks_newsletter(
                json_input_to_summarize={"discussions": []}
            )

    def test_langtalks_newsletter_builds_correct_input(self):
        """Test that LangTalks newsletter builds correct input structure."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        result = provider._get_input_for_generate_content_wa_community_langtalks_newsletter(
            json_input_to_summarize={"discussions": [{"title": "Test"}]},
            examples=["Example 1", "Example 2"]
        )

        assert "model" in result
        assert "messages" in result
        # Should have system + examples + user message
        assert len(result["messages"]) >= 3


@requires_docker
class TestOpenAIProviderGetInputByPurpose:
    """Test OpenAIProvider _get_input_by_purpose method."""

    def test_unknown_purpose_raises_error(self):
        """Test that unknown purpose raises ValueError."""
        from utils.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with pytest.raises(Exception):
            provider._get_input_by_purpose(
                purpose="unknown_purpose",
                call_type="structured_output"
            )

    def test_valid_purpose_returns_input(self):
        """Test that valid purpose returns input dictionary."""
        from utils.llm.openai_provider import OpenAIProvider
        from constants import LlmInputPurposes

        provider = OpenAIProvider()

        result = provider._get_input_by_purpose(
            purpose=LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES,
            call_type="structured_output",
            content_batch=[{"id": "1", "content": "Test"}]
        )

        assert isinstance(result, dict)
        assert "model" in result
        assert "messages" in result


@requires_docker
class TestOpenAIProviderCallWithStructuredOutput:
    """Test OpenAIProvider call_with_structured_output method."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"})
    @patch('utils.llm.openai_provider.AsyncOpenAI')
    async def test_call_with_structured_output_success(self, mock_openai_class):
        """Test successful structured output call."""
        from utils.llm.openai_provider import OpenAIProvider
        from constants import LlmInputPurposes

        # Setup mock with async create
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"messages": [{"content": "translated"}]}'))
        ]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        # Create mock schema
        class MockSchema:
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {"messages": {"type": "array"}}}

        result = await provider.call_with_structured_output(
            purpose=LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES,
            response_schema=MockSchema,
            content_batch=[{"id": "1", "content": "Test"}]
        )

        assert result == {"messages": [{"content": "translated"}]}

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"})
    @patch('utils.llm.openai_provider.AsyncOpenAI')
    async def test_call_with_structured_output_invalid_json_raises_error(self, mock_openai_class):
        """Test that invalid JSON response raises exception."""
        from utils.llm.openai_provider import OpenAIProvider
        from constants import LlmInputPurposes

        # Setup mock with async create
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='not valid json'))
        ]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with pytest.raises(Exception, match="Failed to parse LLM response"):
            await provider.call_with_structured_output(
                purpose=LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES,
                response_schema=MagicMock(),
                content_batch=[{"id": "1", "content": "Test"}]
            )


# ============================================================================
# PROMPT TESTS
# ============================================================================

@requires_docker
class TestTranslateMessagesPrompt:
    """Test translate messages prompt."""

    def test_prompt_exists(self):
        """Test that prompt constant exists."""
        from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT
        assert TRANSLATE_MESSAGES_PROMPT is not None

    def test_prompt_has_placeholders(self):
        """Test that prompt has required placeholders."""
        from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT

        assert "{translate_from}" in TRANSLATE_MESSAGES_PROMPT
        assert "{translate_to}" in TRANSLATE_MESSAGES_PROMPT

    def test_prompt_can_be_formatted(self):
        """Test that prompt can be formatted with values."""
        from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT

        formatted = TRANSLATE_MESSAGES_PROMPT.format(
            translate_from="hebrew",
            translate_to="english"
        )

        assert "hebrew" in formatted
        assert "english" in formatted
        assert "{" not in formatted  # No remaining placeholders


@requires_docker
class TestTranslateNewsletterPrompt:
    """Test translate newsletter prompt."""

    def test_prompt_exists(self):
        """Test that prompt constant exists."""
        from utils.llm.prompts.translation.translate_newsletter import TRANSLATE_NEWSLETTER_PROMPT
        assert TRANSLATE_NEWSLETTER_PROMPT is not None

    def test_prompt_has_placeholders(self):
        """Test that prompt has required placeholders."""
        from utils.llm.prompts.translation.translate_newsletter import TRANSLATE_NEWSLETTER_PROMPT

        assert "{desired_language}" in TRANSLATE_NEWSLETTER_PROMPT


@requires_docker
class TestSeparateDiscussionsPrompt:
    """Test separate discussions prompt."""

    def test_prompt_exists(self):
        """Test that prompt constant exists."""
        from utils.llm.prompts.discussion_separation.separate_discussions import SEPARATE_DISCUSSIONS_PROMPT
        assert SEPARATE_DISCUSSIONS_PROMPT is not None

    def test_prompt_has_placeholders(self):
        """Test that prompt has required placeholders."""
        from utils.llm.prompts.discussion_separation.separate_discussions import SEPARATE_DISCUSSIONS_PROMPT

        assert "{chat_name}" in SEPARATE_DISCUSSIONS_PROMPT


@requires_docker
class TestLangTalksNewsletterPrompt:
    """Test LangTalks newsletter prompt."""

    def test_prompt_exists(self):
        """Test that prompt constant exists."""
        from utils.llm.prompts.newsletter_generation.langtalks_newsletter import LANGTALKS_NEWSLETTER_PROMPT
        assert LANGTALKS_NEWSLETTER_PROMPT is not None

    def test_worth_mentioning_variants_exist(self):
        """Test that worth mentioning variants exist."""
        from utils.llm.prompts.newsletter_generation.langtalks_newsletter import (
            WORTH_MENTIONING_WITH_CANDIDATES,
            WORTH_MENTIONING_WITHOUT_CANDIDATES
        )

        assert WORTH_MENTIONING_WITH_CANDIDATES is not None
        assert WORTH_MENTIONING_WITHOUT_CANDIDATES is not None

    def test_prompt_has_placeholders(self):
        """Test that prompt has required placeholders."""
        from utils.llm.prompts.newsletter_generation.langtalks_newsletter import LANGTALKS_NEWSLETTER_PROMPT

        assert "{worth_mentioning_guidance}" in LANGTALKS_NEWSLETTER_PROMPT


@requires_docker
class TestRankDiscussionsPrompt:
    """Test rank discussions prompt."""

    def test_prompt_exists(self):
        """Test that prompt constant exists."""
        from utils.llm.prompts.ranking.rank_discussions import RANK_DISCUSSIONS_PROMPT
        assert RANK_DISCUSSIONS_PROMPT is not None

    def test_repetition_sections_exist(self):
        """Test that repetition analysis sections exist."""
        from utils.llm.prompts.ranking.rank_discussions import (
            REPETITION_ANALYSIS_SECTION,
            NO_PREVIOUS_NEWSLETTERS_SECTION
        )

        assert REPETITION_ANALYSIS_SECTION is not None
        assert NO_PREVIOUS_NEWSLETTERS_SECTION is not None


# ============================================================================
# CONSTANTS TESTS
# ============================================================================

@requires_docker
class TestLlmInputPurposes:
    """Test LlmInputPurposes enum."""

    def test_enum_exists(self):
        """Test that enum exists."""
        from constants import LlmInputPurposes
        assert LlmInputPurposes is not None

    def test_all_purposes_defined(self):
        """Test that all expected purposes are defined."""
        from constants import LlmInputPurposes

        assert hasattr(LlmInputPurposes, 'SEPARATE_DISCUSSIONS')
        assert hasattr(LlmInputPurposes, 'TRANSLATE_WHATSAPP_GROUP_MESSAGES')
        assert hasattr(LlmInputPurposes, 'TRANSLATE_SUMMARY')
        assert hasattr(LlmInputPurposes, 'GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER')

    def test_purposes_are_strings(self):
        """Test that purposes are string enums."""
        from constants import LlmInputPurposes

        assert isinstance(LlmInputPurposes.SEPARATE_DISCUSSIONS.value, str)
        assert str(LlmInputPurposes.SEPARATE_DISCUSSIONS) == LlmInputPurposes.SEPARATE_DISCUSSIONS.value
