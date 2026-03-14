"""
LangChain Chat Model Factory

Provider-aware factory that returns the correct LangChain BaseChatModel
for the configured LLM provider. Replaces hardcoded ChatOpenAI usage
throughout the codebase.

Usage:
    from utils.llm.chat_model_factory import create_chat_model

    llm = create_chat_model(model=settings.llm.ranking_model, temperature=0.2)
"""

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from config import get_settings
from constants import DEFAULT_LLM_PROVIDER, ANTHROPIC_LLM_PROVIDER, GEMINI_LLM_PROVIDER

logger = logging.getLogger(__name__)


def create_chat_model(
    model: str,
    temperature: float = 0.2,
    provider: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """
    Create a LangChain chat model for the configured (or specified) provider.

    Args:
        model: Model name (must match the provider, e.g. "gpt-4o" for OpenAI,
               "claude-sonnet-4-20250514" for Anthropic)
        temperature: Sampling temperature
        provider: Override the provider from settings. If None, uses settings.llm.provider.
        **kwargs: Additional provider-specific arguments

    Returns:
        LangChain BaseChatModel instance

    Raises:
        ValueError: If the provider is unknown
        RuntimeError: If the provider's langchain package is not installed
    """
    resolved_provider = provider or get_settings().llm.provider

    if resolved_provider == DEFAULT_LLM_PROVIDER:
        return _create_openai_model(model, temperature, **kwargs)
    elif resolved_provider == ANTHROPIC_LLM_PROVIDER:
        return _create_anthropic_model(model, temperature, **kwargs)
    elif resolved_provider == GEMINI_LLM_PROVIDER:
        return _create_gemini_model(model, temperature, **kwargs)
    else:
        raise ValueError(f"Unknown LLM provider '{resolved_provider}'. " f"Available: {DEFAULT_LLM_PROVIDER}, {ANTHROPIC_LLM_PROVIDER}, {GEMINI_LLM_PROVIDER}")


def _create_openai_model(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    """Create a ChatOpenAI instance."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise RuntimeError("langchain-openai is required for OpenAI provider. Install with: uv add langchain-openai") from e

    model_kwargs = kwargs.pop("model_kwargs", {})
    return ChatOpenAI(model=model, temperature=temperature, model_kwargs=model_kwargs, **kwargs)


def _create_anthropic_model(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    """Create a ChatAnthropic instance."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise RuntimeError("langchain-anthropic is required for Anthropic provider. Install with: uv add langchain-anthropic") from e

    # Anthropic doesn't use model_kwargs for response_format — structured output
    # is handled via .with_structured_output() or tool_choice at the chain level.
    # Strip model_kwargs that are OpenAI-specific.
    kwargs.pop("model_kwargs", None)

    settings = get_settings()
    return ChatAnthropic(
        model=model,
        temperature=temperature,
        max_tokens=settings.llm.anthropic_max_tokens,
        **kwargs,
    )


def _create_gemini_model(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    """Create a ChatGoogleGenerativeAI instance."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise RuntimeError("langchain-google-genai is required for Gemini provider. Install with: uv add langchain-google-genai") from e

    kwargs.pop("model_kwargs", None)
    return ChatGoogleGenerativeAI(model=model, temperature=temperature, **kwargs)
