"""
Batch API Providers

Provider implementations for batch API operations.

Available Providers:
- OpenAIBatchProvider: OpenAI Batch API (50% discount)
- AnthropicBatchProvider: Anthropic Message Batches (50% discount)
- GeminiBatchProvider: Google Gemini Batch Mode (50% discount)
"""

from typing import Literal

from ..interface import BatchAPIProvider
from constants import DEFAULT_LLM_PROVIDER, ANTHROPIC_LLM_PROVIDER, GEMINI_LLM_PROVIDER

# Import available providers
from .openai_provider import OpenAIBatchProvider
from .anthropic_provider import AnthropicBatchProvider
from .gemini_provider import GeminiBatchProvider

# Provider registry
_PROVIDERS: dict[str, type[BatchAPIProvider]] = {
    DEFAULT_LLM_PROVIDER: OpenAIBatchProvider,
    ANTHROPIC_LLM_PROVIDER: AnthropicBatchProvider,
    GEMINI_LLM_PROVIDER: GeminiBatchProvider,
}


def get_provider(provider_name: Literal["openai", "anthropic", "gemini"] = DEFAULT_LLM_PROVIDER, model: str | None = None, **kwargs) -> BatchAPIProvider:
    """
    Get a batch API provider by name.

    Args:
        provider_name: Provider to use ('openai', 'anthropic', 'gemini')
        model: Optional model override
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BatchAPIProvider instance

    Raises:
        ValueError: If provider not available
    """
    if provider_name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Provider '{provider_name}' not available. " f"Available providers: {available}")

    provider_class = _PROVIDERS[provider_name]
    return provider_class(model=model, **kwargs)


def list_providers() -> list[str]:
    """Return list of available provider names."""
    return list(_PROVIDERS.keys())


__all__ = [
    "OpenAIBatchProvider",
    "AnthropicBatchProvider",
    "GeminiBatchProvider",
    "get_provider",
    "list_providers",
]
