"""
Anthropic LLM Provider

Implementation of the LLM provider interface for Anthropic Claude models.
Uses tool_use for structured output and the Messages API for all calls.
Instrumented with Langfuse for tracing and cost tracking.
"""

import json
import logging
import os
from typing import Any
from collections.abc import Callable

import anthropic
from anthropic import AsyncAnthropic
from pydantic import Field

from config import get_settings
from utils.llm.retry import with_retry
from constants import (
    LlmInputPurposes,
    LLMCallType,
    MessageRole,
)
from custom_types.exceptions import (
    LLMError,
    LLMResponseError,
    ConfigurationError,
    ValidationError,
)
from utils.llm.interface import LLMProviderInterface
from utils.llm.json_parser import parse_json_response
from utils.llm.prompt_inputs import PromptInputBuilderMixin
from observability.llm import is_langfuse_enabled

# Conditional import for Langfuse decorators
try:
    from langfuse.decorators import observe, langfuse_context

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

    def observe(**kwargs):  # No-op decorator
        def _noop(func):
            return func

        return _noop

    langfuse_context = None


logger = logging.getLogger(__name__)


def _pydantic_to_tool(response_schema: Any, tool_name: str = "structured_response") -> dict:
    """Convert a Pydantic model to an Anthropic tool definition.

    Strips 'additionalProperties' and 'strict' that Anthropic doesn't support.
    """
    if hasattr(response_schema, "model_json_schema"):
        raw_schema = response_schema.model_json_schema()
    elif hasattr(response_schema, "schema"):
        raw_schema = response_schema.schema()
    else:
        raw_schema = response_schema

    cleaned = _clean_schema(raw_schema)

    return {
        "name": tool_name,
        "description": "Return the structured response in JSON format.",
        "input_schema": cleaned,
    }


def _clean_schema(schema: dict) -> dict:
    """Remove additionalProperties/strict from schema for Anthropic compatibility."""
    cleaned = {}
    for key, value in schema.items():
        if key in ("additionalProperties", "strict"):
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_schema(item) if isinstance(item, dict) else item for item in value]
        else:
            cleaned[key] = value
    return cleaned


def _extract_system_and_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Separate system message from user/assistant messages.

    Anthropic requires system as a separate parameter.
    """
    system_content = None
    non_system = []

    for msg in messages:
        if msg.get("role") == MessageRole.SYSTEM:
            system_content = msg.get("content", "")
        else:
            non_system.append(msg)

    return system_content, non_system


class AnthropicProvider(PromptInputBuilderMixin, LLMProviderInterface):
    """
    Anthropic LLM provider implementation.

    Provides methods for making calls to Anthropic Claude models with support for
    structured output (via tool_use) and various use-case specific prompts.
    """

    INPUT_PURPOSE_MAP: dict[str, dict[str, Callable[..., dict[str, Any]]]] = Field(default_factory=dict)
    anthropic_client: AsyncAnthropic | None = Field(default=None)

    def __init__(self, **kwargs: Any) -> None:
        try:
            super().__init__(**kwargs)
            self.anthropic_client = None
            self.INPUT_PURPOSE_MAP = {
                LLMCallType.STRUCTURED_OUTPUT: {
                    LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES: self._get_input_for_translate_whatsapp_group_messages,
                    LlmInputPurposes.SEPARATE_DISCUSSIONS: self._get_input_for_separate_whatsapp_group_message_discussions,
                    LlmInputPurposes.TRANSLATE_SUMMARY: self._get_input_for_translate_newsletter_summary,
                    LlmInputPurposes.TRANSLATE_NEWSLETTER_STRUCTURED: self._get_input_for_translate_newsletter_structured,
                    LlmInputPurposes.GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER: self._get_input_for_generate_content_wa_community_langtalks_newsletter,
                }
            }
        except Exception as e:
            error_message = f"Error while initializing Anthropic provider: {e}"
            logger.error(error_message)
            raise LLMError(error_message) from e

    def _get_anthropic_client(self) -> AsyncAnthropic:
        try:
            if not self.anthropic_client:
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ConfigurationError("ANTHROPIC_API_KEY not found in environment variables. " "Set it in .env or as an environment variable.")
                # Explicit timeout: the SDK default is up to ~10 min, far too
                # long for interactive RAG/agent paths; bound it from config.
                self.anthropic_client = AsyncAnthropic(api_key=api_key, timeout=get_settings().llm.request_timeout_seconds)
            return self.anthropic_client
        except ConfigurationError:
            raise
        except Exception as e:
            error_message = f"Error while initializing Anthropic client: {e}"
            logger.error(error_message)
            raise LLMError(error_message) from e

    # =========================================================================
    # Langfuse Observation Helpers
    # =========================================================================

    def _update_langfuse_input(self, model: str, messages: list, purpose: str, temperature: float, response_schema: type | None = None) -> None:
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            metadata = {"purpose": str(purpose), "temperature": temperature}
            if response_schema:
                metadata["response_schema"] = getattr(response_schema, "__name__", "ResponseSchema")
            langfuse_context.update_current_observation(model=model, input=messages, metadata=metadata)
        except Exception as trace_err:
            logging.debug(f"Failed to update Langfuse observation input: {trace_err}")

    def _update_langfuse_output(self, content: str, usage: Any) -> None:
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            langfuse_context.update_current_observation(
                output=content,
                usage={
                    "input": getattr(usage, "input_tokens", 0),
                    "output": getattr(usage, "output_tokens", 0),
                    "total": getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0),
                    "unit": "TOKENS",
                },
            )
        except Exception as trace_err:
            logging.debug(f"Failed to update Langfuse observation output: {trace_err}")

    def _update_langfuse_error(self, error: Exception) -> None:
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            langfuse_context.update_current_observation(level="ERROR", status_message=str(error))
        except Exception as trace_err:
            # Observability failures must never mask the underlying LLM error,
            # but they should not vanish silently either — a broken tracing
            # pipeline needs to be diagnosable.
            logging.debug(f"Failed to update Langfuse error observation: {trace_err}")

    # =========================================================================
    # Public API methods
    # =========================================================================

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="anthropic_structured_output")
    async def call_with_structured_output(self, purpose: str, response_schema: Any, **kwargs) -> Any:
        try:
            client = self._get_anthropic_client()
            purpose_specific_input = self._get_input_by_purpose(purpose, "structured_output", **kwargs)

            settings = get_settings()
            model = purpose_specific_input.get("model", settings.llm.default_model)
            temperature = purpose_specific_input.get("temperature", settings.llm.temperature_json)
            messages = purpose_specific_input.get("messages", [])

            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            # Separate system message
            system_content, non_system_messages = _extract_system_and_messages(messages)

            # Build tool for structured output
            tool_def = _pydantic_to_tool(response_schema)

            create_kwargs = {
                "model": model,
                "max_tokens": settings.llm.anthropic_max_tokens,
                "messages": non_system_messages,
                "temperature": temperature,
                "tools": [tool_def],
                "tool_choice": {"type": "tool", "name": tool_def["name"]},
            }
            if system_content:
                create_kwargs["system"] = system_content

            response = await client.messages.create(**create_kwargs)

            # Extract tool_use content
            for content_block in response.content:
                if content_block.type == "tool_use":
                    content = json.dumps(content_block.input, ensure_ascii=False)
                    self._update_langfuse_output(content, response.usage)
                    return content_block.input

            # Fallback: text content
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            if text_parts:
                content = text_parts[0]
                self._update_langfuse_output(content, response.usage)
                parsed = json.loads(content)
                return parsed

            raise LLMResponseError("No tool_use or text content in Anthropic response")

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Anthropic response as JSON: {e}") from e
        except anthropic.APIError as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Anthropic API error in call_with_structured_output: {e}") from e
        except (ConfigurationError, ValidationError):
            raise
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in call_with_structured_output: {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="anthropic_structured_output_generic")
    async def call_with_structured_output_generic(self, messages: list[dict], response_schema: type, purpose: str = "generic", model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        try:
            client = self._get_anthropic_client()
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            logger.info(f"[{purpose}] Making Anthropic structured output call with model={model}")

            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            system_content, non_system_messages = _extract_system_and_messages(messages)
            tool_def = _pydantic_to_tool(response_schema)

            create_kwargs = {
                "model": model,
                "max_tokens": settings.llm.anthropic_max_tokens,
                "messages": non_system_messages,
                "temperature": temperature,
                "tools": [tool_def],
                "tool_choice": {"type": "tool", "name": tool_def["name"]},
            }
            if system_content:
                create_kwargs["system"] = system_content

            response = await client.messages.create(**create_kwargs)

            for content_block in response.content:
                if content_block.type == "tool_use":
                    content = json.dumps(content_block.input, ensure_ascii=False)
                    self._update_langfuse_output(content, response.usage)
                    return content_block.input

            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            if text_parts:
                content = text_parts[0]
                self._update_langfuse_output(content, response.usage)
                return json.loads(content)

            raise LLMResponseError(f"No tool_use or text content in Anthropic response ({purpose})")

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Anthropic response as JSON ({purpose}): {e}") from e
        except anthropic.APIError as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Anthropic API error in call_with_structured_output_generic ({purpose}): {e}") from e
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in call_with_structured_output_generic ({purpose}): {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="anthropic_json_output")
    async def call_with_json_output(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        try:
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            client = self._get_anthropic_client()
            logger.info(f"[{purpose}] Making Anthropic JSON output call with model={model}")

            # NOTE: Claude 4.6+ rejects assistant-prefill ("conversation must end
            # with a user message"). We instead rely on a strong instruction and a
            # tolerant extractor that strips code fences and slices to the outermost
            # JSON object. No fallbacks: if parsing fails, we raise loudly.
            user_content = f"{prompt}\n\nRespond with a single valid JSON object and nothing else. Do not wrap it in markdown code fences."
            messages = [{"role": MessageRole.USER, "content": user_content}]
            self._update_langfuse_input(model, messages, purpose, temperature)

            response = await client.messages.create(
                model=model,
                max_tokens=settings.llm.anthropic_max_tokens,
                messages=messages,
                temperature=temperature,
            )

            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            if not text_parts:
                raise LLMResponseError(f"Empty Anthropic text response in call_with_json_output ({purpose})")
            raw_text = text_parts[0]
            self._update_langfuse_output(raw_text, response.usage)

            parsed = parse_json_response(raw_text)
            return parsed

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Anthropic response as JSON ({purpose}): {e}") from e
        except anthropic.APIError as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Anthropic API error in call_with_json_output ({purpose}): {e}") from e
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in call_with_json_output ({purpose}): {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="anthropic_simple")
    async def call_simple(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> str:
        try:
            settings = get_settings()
            model = model or settings.llm.default_model_mini
            temperature = temperature if temperature is not None else settings.llm.temperature_simple

            client = self._get_anthropic_client()
            logger.info(f"[{purpose}] Making Anthropic simple call with model={model}")

            messages = [{"role": MessageRole.USER, "content": prompt}]
            self._update_langfuse_input(model, messages, purpose, temperature)

            response = await client.messages.create(
                model=model,
                max_tokens=settings.llm.anthropic_max_tokens,
                messages=messages,
                temperature=temperature,
            )

            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            content = text_parts[0] if text_parts else ""
            self._update_langfuse_output(content, response.usage)
            return content

        except anthropic.APIError as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Anthropic API error in call_simple ({purpose}): {e}") from e
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in call_simple ({purpose}): {e}") from e

    # =========================================================================
    # Purpose-map routing (internal)
    # =========================================================================

    def _get_input_by_purpose(self, purpose: str, call_type: str, **kwargs) -> dict[str, Any]:
        try:
            if purpose not in self.INPUT_PURPOSE_MAP.get(call_type, {}):
                raise ValidationError(f"Purpose '{purpose}' not found in INPUT_PURPOSE_MAP")
            function_to_call = self.INPUT_PURPOSE_MAP[call_type][purpose]
            return function_to_call(**kwargs)
        except ValidationError:
            raise
        except Exception as e:
            raise LLMError(f"Error in _get_input_by_purpose: {e}") from e
