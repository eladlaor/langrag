"""
Batch API Module

Provider-agnostic batch API support for cost-efficient LLM operations.

All major providers offer ~50% cost savings for batch operations:
- OpenAI: Batch API (50% discount, 24hr SLA)
- Anthropic: Message Batches (50% discount, stacks with prompt caching)
- Gemini: Batch Mode (50% discount)

Usage:
    from utils.llm.batch import get_provider, BatchRequest

    # Get a provider
    provider = get_provider("openai")

    # Create requests
    requests = [
        BatchRequest(
            custom_id="req_1",
            messages=[
                {"role": "system", "content": "You are a translator."},
                {"role": "user", "content": "Translate to English: Shalom"}
            ]
        ),
        # ... more requests
    ]

    # Execute batch (blocking)
    result = provider.execute_batch(requests, timeout_minutes=60)

    # Process results
    for req_result in result.results:
        if req_result.success:
            logger.info(f"{req_result.custom_id}: {req_result.content}")
        else:
            logger.error(f"{req_result.custom_id} failed: {req_result.error}")
"""

# Types
from .types import (
    BatchInfo,
    BatchRequest,
    BatchRequestResult,
    BatchResult,
    BatchStatus,
)

# Interface
from .interface import BatchAPIProvider

# Provider factory
from .providers import get_provider, list_providers

# Specific providers (for direct import if needed)
from .providers.openai_provider import OpenAIBatchProvider
from .providers.anthropic_provider import AnthropicBatchProvider
from .providers.gemini_provider import GeminiBatchProvider

# Domain-specific wrappers
from .batch_translator import BatchTranslator

__all__ = [
    # Types
    "BatchInfo",
    "BatchRequest",
    "BatchRequestResult",
    "BatchResult",
    "BatchStatus",
    # Interface
    "BatchAPIProvider",
    # Factory
    "get_provider",
    "list_providers",
    # Providers
    "OpenAIBatchProvider",
    "AnthropicBatchProvider",
    "GeminiBatchProvider",
    # Domain-specific wrappers
    "BatchTranslator",
]
