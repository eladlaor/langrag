from abc import ABC, abstractmethod
from typing import Any

from custom_types.common import CustomBaseModel


class LLMProviderInterface(ABC, CustomBaseModel):
    """
    Abstract interface for LLM providers.

    Defines the contract that all LLM provider implementations must follow.
    Uses the Strategy pattern to allow swapping providers without changing client code.

    All methods are async to avoid blocking the event loop during LLM API calls.

    All implementations must support four call types:
    - call_with_structured_output: Purpose-based structured output (legacy purpose-map callers)
    - call_with_structured_output_generic: Generic structured output with pre-built messages
    - call_with_json_output: JSON output without strict schema
    - call_simple: Plain text response
    """

    @abstractmethod
    async def call_with_structured_output(self, purpose: str, response_schema: Any, **kwargs) -> Any:
        """
        Purpose-based structured output call.

        Uses internal purpose-map to build messages from kwargs.

        Args:
            purpose: The purpose/intent of the call, used to select appropriate prompts
            response_schema: Pydantic model or JSON schema defining expected output
            **kwargs: Additional arguments specific to the call

        Returns:
            Parsed structured response matching the schema
        """
        ...

    @abstractmethod
    async def call_with_structured_output_generic(self, messages: list[dict], response_schema: type, purpose: str = "generic", model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        """
        Generic structured output with pre-built messages.

        No format-specific logic — just sends messages to LLM and returns parsed JSON.

        Args:
            messages: Pre-built message list
            response_schema: Pydantic model for response structure
            purpose: Purpose identifier for logging/tracing
            model: LLM model to use (default from config)
            temperature: Temperature setting (default from config)

        Returns:
            Parsed JSON response as dict
        """
        ...

    @abstractmethod
    async def call_with_json_output(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        """
        JSON output without strict schema.

        Args:
            purpose: Purpose identifier (for logging)
            prompt: The full prompt to send to the LLM
            model: Model to use (default from config)
            temperature: Temperature setting (default from config)

        Returns:
            Parsed JSON response as dict
        """
        ...

    @abstractmethod
    async def call_simple(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> str:
        """
        Plain text response.

        Args:
            purpose: Purpose identifier (for logging)
            prompt: The full prompt to send to the LLM
            model: Model to use (default from config)
            temperature: Temperature setting (default from config)

        Returns:
            Text response as string
        """
        ...

    async def call_with_vision(
        self,
        purpose: str,
        prompt: str,
        image_data: bytes,
        image_media_type: str = "image/jpeg",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Describe or analyze an image using vision capabilities.

        Default implementation raises NotImplementedError.
        Providers that support vision should override this method.

        Args:
            purpose: Purpose identifier (for logging)
            prompt: Text prompt to send alongside the image
            image_data: Raw image bytes
            image_media_type: MIME type of the image
            model: Vision model to use
            temperature: Temperature setting
            max_tokens: Maximum tokens for response

        Returns:
            Text description of the image
        """
        raise NotImplementedError(f"{type(self).__name__} does not support vision calls")
