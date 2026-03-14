"""
LLM Provider Abstraction Layer

Provides a unified interface for interacting with various LLM providers
using the Strategy pattern. Supports:
- OpenAI
- Anthropic
- Gemini

Usage:
    from utils.llm import get_llm_caller

    # Get the singleton provider (determined by LLM_PROVIDER env var)
    caller = get_llm_caller()

    # Make calls
    result = caller.call_with_structured_output(
        purpose="translate_messages",
        response_schema=MyResponseSchema,
        content_batch=messages
    )
"""

from utils.llm.interface import LLMProviderInterface
from utils.llm.factory import LLMProviderFactory
from utils.llm.singleton import get_llm_caller
from utils.llm.openai_provider import OpenAIProvider, OpenaiCaller

__all__ = [
    "LLMProviderInterface",
    "LLMProviderFactory",
    "get_llm_caller",
    "OpenAIProvider",
    "OpenaiCaller",  # Backward compatibility
]
