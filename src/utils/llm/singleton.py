"""
LLM Provider Singleton

Provides a cached singleton LLM provider instance, determined by the
LLM_PROVIDER environment variable (via config.py).

Usage:
    from utils.llm import get_llm_caller

    caller = get_llm_caller()
    result = caller.call_with_json_output(purpose="...", prompt="...")
"""

import logging
from functools import lru_cache

from config import get_settings
from utils.llm.factory import LLMProviderFactory
from utils.llm.interface import LLMProviderInterface

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm_caller() -> LLMProviderInterface:
    """Get the singleton LLM provider instance.

    The provider is determined by the LLM_PROVIDER env var (default: openai).
    Created once and cached for the lifetime of the process.

    Returns:
        LLMProviderInterface singleton instance

    Raises:
        ValueError: If the configured provider is not registered
        ConfigurationError: If required API keys are missing
    """
    settings = get_settings()
    provider_name = settings.llm.provider

    logger.info(f"Initializing LLM provider singleton: {provider_name}")
    return LLMProviderFactory.create(provider_name)
