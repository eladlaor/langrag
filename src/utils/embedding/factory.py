"""
Embedding Provider Factory

Factory for creating embedding provider instances.
Supports registration of new providers and lazy loading.
"""

import logging

from utils.embedding.interface import EmbeddingProviderInterface
from constants import DEFAULT_LLM_PROVIDER

logger = logging.getLogger(__name__)


class EmbeddingProviderFactory:
    """
    Factory for creating embedding provider instances.

    Supports registration of new providers and lazy loading to avoid
    import overhead when a provider isn't used.
    """

    _providers: dict[str, type[EmbeddingProviderInterface]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[EmbeddingProviderInterface]) -> None:
        """
        Register a provider class with a name.

        Args:
            name: Name to register the provider under (e.g., "openai", "cohere")
            provider_class: The provider class to register
        """
        cls._providers[name] = provider_class
        logger.debug(f"Registered embedding provider: {name}")

    @classmethod
    def create(cls, provider_name: str = DEFAULT_LLM_PROVIDER, **kwargs) -> EmbeddingProviderInterface:
        """
        Create an embedding provider instance.

        Args:
            provider_name: Name of the provider to create (default: "openai")
            **kwargs: Additional arguments passed to the provider constructor

        Returns:
            EmbeddingProviderInterface instance

        Raises:
            ValueError: If the provider is not registered
        """
        if not cls._providers:
            cls._register_default_providers()

        if provider_name not in cls._providers:
            available = list(cls._providers.keys())
            raise ValueError(f"Embedding provider '{provider_name}' not found. " f"Available providers: {available}")

        provider_class = cls._providers[provider_name]
        return provider_class(**kwargs)

    @classmethod
    def _register_default_providers(cls) -> None:
        """Register default providers on first use."""
        try:
            from utils.embedding.openai_embedder import OpenAIEmbedder

            cls.register(DEFAULT_LLM_PROVIDER, OpenAIEmbedder)
        except ImportError:
            logger.warning("OpenAI embedding provider not available")

        # Future providers can be registered here:
        # try:
        #     from utils.embedding.cohere_embedder import CohereEmbedder
        #     cls.register("cohere", CohereEmbedder)
        # except ImportError:
        #     logger.warning("Cohere embedding provider not available")
