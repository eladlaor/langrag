import logging

from utils.llm.interface import LLMProviderInterface
from constants import DEFAULT_LLM_PROVIDER, ANTHROPIC_LLM_PROVIDER, GEMINI_LLM_PROVIDER


logger = logging.getLogger(__name__)


class LLMProviderFactory:
    """
    Factory for creating LLM provider instances.

    Supports registration of new providers and lazy loading to avoid
    import overhead when a provider isn't used.
    """

    _providers: dict[str, type[LLMProviderInterface]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[LLMProviderInterface]) -> None:
        """Register a provider class with a name."""
        cls._providers[name] = provider_class
        logger.debug(f"Registered LLM provider: {name}")

    @classmethod
    def create(cls, provider_name: str = DEFAULT_LLM_PROVIDER, **kwargs) -> LLMProviderInterface:
        """
        Create an LLM provider instance.

        Args:
            provider_name: Name of the provider to create (default: "openai")
            **kwargs: Additional arguments passed to the provider constructor

        Returns:
            LLMProviderInterface instance

        Raises:
            ValueError: If the provider is not registered
        """
        # Lazy load providers if not registered
        if not cls._providers:
            cls._register_default_providers()

        if provider_name not in cls._providers:
            available = list(cls._providers.keys())
            raise ValueError(f"LLM provider '{provider_name}' not found. " f"Available providers: {available}")

        provider_class = cls._providers[provider_name]
        return provider_class(**kwargs)

    @classmethod
    def _register_default_providers(cls) -> None:
        """Register default providers on first use."""
        try:
            from utils.llm.openai_provider import OpenAIProvider

            cls.register(DEFAULT_LLM_PROVIDER, OpenAIProvider)
        except ImportError:
            logger.warning("OpenAI provider not available")

        try:
            from utils.llm.anthropic_provider import AnthropicProvider

            cls.register(ANTHROPIC_LLM_PROVIDER, AnthropicProvider)
        except ImportError:
            logger.warning("Anthropic provider not available")

        try:
            from utils.llm.gemini_provider import GeminiProvider

            cls.register(GEMINI_LLM_PROVIDER, GeminiProvider)
        except ImportError:
            logger.warning("Gemini provider not available")
