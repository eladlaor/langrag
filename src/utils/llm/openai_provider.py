"""
OpenAI LLM Provider

Implementation of the LLM provider interface for OpenAI models.
Uses prompts from utils/llm/prompts/ for all LLM interactions.
Instrumented with Langfuse for tracing and cost tracking.
"""

import json
import logging
import os
from typing import Any
from collections.abc import Callable

import openai
from openai import AsyncOpenAI
from pydantic import Field

from config import get_settings
from utils.llm.retry import with_retry
from constants import LlmInputPurposes, LLMCallType, DEFAULT_LANGUAGE, DEFAULT_HTML_LANGUAGE, MessageRole
from custom_types.exceptions import (
    LLMError,
    LLMResponseError,
    ConfigurationError,
    ValidationError,
)
from custom_types.field_keys import LlmInputKeys
from utils.llm.interface import LLMProviderInterface
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
from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT
from utils.llm.prompts.translation.translate_newsletter import TRANSLATE_NEWSLETTER_PROMPT
from utils.llm.prompts.discussion_separation.separate_discussions import SEPARATE_DISCUSSIONS_PROMPT
from utils.llm.prompts.newsletter_generation.langtalks_newsletter import (
    LANGTALKS_NEWSLETTER_PROMPT,
    WORTH_MENTIONING_WITH_CANDIDATES,
    WORTH_MENTIONING_WITHOUT_CANDIDATES,
)


def _enforce_strict_schema(schema: dict) -> None:
    """Recursively add 'additionalProperties': false to all object-type schemas.

    OpenAI strict mode requires this on every object in the JSON schema.
    Modifies the schema dict in-place.
    """
    if not isinstance(schema, dict):
        return
    # OpenAI strict mode: $ref cannot coexist with other keywords like 'description'
    if "$ref" in schema:
        keys_to_remove = [k for k in schema if k != "$ref"]
        for k in keys_to_remove:
            del schema[k]
        return
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        # Ensure all properties are listed in 'required' for strict mode
        props = schema.get("properties", {})
        if props:
            schema["required"] = list(props.keys())
    for key in ("properties", "$defs", "definitions"):
        container = schema.get(key, {})
        if isinstance(container, dict):
            for child in container.values():
                _enforce_strict_schema(child)
    for key in ("items", "anyOf", "oneOf", "allOf"):
        value = schema.get(key)
        if isinstance(value, dict):
            _enforce_strict_schema(value)
        elif isinstance(value, list):
            for item in value:
                _enforce_strict_schema(item)


class OpenAIProvider(LLMProviderInterface):
    """
    OpenAI LLM provider implementation.

    Provides methods for making calls to OpenAI models with support for
    structured output and various use-case specific prompts.

    Attributes:
        INPUT_PURPOSE_MAP: Maps call types to purpose-specific input generators.
        openai_client: Cached OpenAI client instance.
    """

    INPUT_PURPOSE_MAP: dict[str, dict[str, Callable[..., dict[str, Any]]]] = Field(default_factory=dict)
    openai_client: AsyncOpenAI | None = Field(default=None)

    def __init__(self, **kwargs: Any) -> None:
        try:
            super().__init__(**kwargs)
            self.openai_client = None
            self.INPUT_PURPOSE_MAP = {
                LLMCallType.STRUCTURED_OUTPUT: {
                    LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES: self._get_input_for_translate_whatsapp_group_messages,
                    LlmInputPurposes.SEPARATE_DISCUSSIONS: self._get_input_for_separate_whatsapp_group_message_discussions,
                    LlmInputPurposes.TRANSLATE_SUMMARY: self._get_input_for_translate_newsletter_summary,
                    LlmInputPurposes.GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER: self._get_input_for_generate_content_wa_community_langtalks_newsletter,
                }
            }

        except Exception as e:
            error_message = f"Error while initializing OpenAI provider: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_openai_client(self, **kwargs) -> AsyncOpenAI:
        try:
            if not self.openai_client:
                openai_api_key = os.getenv("OPENAI_API_KEY")
                if not openai_api_key:
                    raise ConfigurationError("OPENAI_API_KEY not found in environment variables. " "Set it in .env or as an environment variable.")

                self.openai_client = AsyncOpenAI(api_key=openai_api_key)

            return self.openai_client

        except ConfigurationError:
            raise  # Re-raise configuration errors as-is
        except Exception as e:
            error_message = f"Error while initializing OpenAI client: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    # =========================================================================
    # Langfuse Observation Helpers
    # =========================================================================

    def _update_langfuse_input(self, model: str, messages: list, purpose: str, temperature: float, response_schema: type | None = None) -> None:
        """Update Langfuse observation with input metadata."""
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            metadata = {
                "purpose": str(purpose),
                "temperature": temperature,
            }
            if response_schema:
                metadata["response_schema"] = getattr(response_schema, "__name__", "ResponseSchema")

            langfuse_context.update_current_observation(model=model, input=messages, metadata=metadata)
        except Exception as trace_err:
            logging.debug(f"Failed to update Langfuse observation input: {trace_err}")

    def _update_langfuse_output(self, content: str, usage: Any) -> None:
        """Update Langfuse observation with output and token usage."""
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            langfuse_context.update_current_observation(
                output=content,
                usage={
                    "input": usage.prompt_tokens if usage else 0,
                    "output": usage.completion_tokens if usage else 0,
                    "total": usage.total_tokens if usage else 0,
                    "unit": "TOKENS",
                },
            )
        except Exception as trace_err:
            logging.debug(f"Failed to update Langfuse observation output: {trace_err}")

    def _update_langfuse_error(self, error: Exception) -> None:
        """Log error to Langfuse observation."""
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            langfuse_context.update_current_observation(level="ERROR", status_message=str(error))
        except Exception:
            pass

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="openai_structured_output")
    async def call_with_structured_output(self, purpose: str, response_schema: Any, **kwargs) -> Any:
        try:
            client = self._get_openai_client()

            purpose_specific_input = self._get_input_by_purpose(purpose, "structured_output", **kwargs)

            # Checking if response_schema is a Pydantic model and converting to dict if needed
            if hasattr(response_schema, "model_json_schema"):
                raw_schema = response_schema.model_json_schema()
            elif hasattr(response_schema, "schema"):
                raw_schema = response_schema.schema()
            else:
                raw_schema = response_schema

            # OpenAI strict mode requires "additionalProperties": false on all object schemas
            _enforce_strict_schema(raw_schema)

            schema_dict = {
                "name": getattr(response_schema, "__name__", "ResponseSchema"),
                "strict": True,
                "schema": raw_schema,
            }

            settings = get_settings()
            model = purpose_specific_input.get("model", settings.llm.default_model)
            messages = purpose_specific_input.get("messages", [])
            temperature = purpose_specific_input.get("temperature", settings.llm.temperature_json)

            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_schema", "json_schema": schema_dict},
            )

            content = response.choices[0].message.content
            logging.debug(f"Raw content from LLM: {content}")

            self._update_langfuse_output(content, response.usage)

            parsed_content = json.loads(content)
            return parsed_content

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            error_message = f"Failed to parse LLM response as JSON: {e}"
            logging.error(error_message)
            raise LLMResponseError(error_message) from e
        except openai.APIError as e:
            self._update_langfuse_error(e)
            error_message = f"OpenAI API error in call_with_structured_output: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e
        except (ConfigurationError, ValidationError):
            raise  # Re-raise configuration/validation errors as-is
        except Exception as e:
            self._update_langfuse_error(e)
            error_message = f"Unexpected error in call_with_structured_output: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="openai_structured_output_generic")
    async def call_with_structured_output_generic(self, messages: list[dict], response_schema: type, purpose: str = "generic", model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        """
        Generic structured output call with pre-built messages.

        Used by newsletter generator with format-owned prompt building.
        No format-specific logic - just sends messages to LLM.

        Args:
            messages: Pre-built message list in OpenAI format
            response_schema: Pydantic model for response structure
            purpose: Purpose identifier for logging/tracing
            model: LLM model to use (default from config)
            temperature: Temperature setting (default from config)

        Returns:
            Parsed JSON response as dict
        """
        try:
            client = self._get_openai_client()
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            # Convert Pydantic model to JSON schema if needed
            if hasattr(response_schema, "model_json_schema"):
                raw_schema = response_schema.model_json_schema()
            elif hasattr(response_schema, "schema"):
                raw_schema = response_schema.schema()
            else:
                raw_schema = response_schema

            _enforce_strict_schema(raw_schema)

            schema_dict = {
                "name": getattr(response_schema, "__name__", "ResponseSchema"),
                "strict": True,
                "schema": raw_schema,
            }

            logging.info(f"[{purpose}] Making structured output call with model={model}")

            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_schema", "json_schema": schema_dict},
            )

            content = response.choices[0].message.content
            logging.debug(f"[{purpose}] Raw response: {content[:500] if content else 'empty'}...")

            self._update_langfuse_output(content, response.usage)

            parsed_content = json.loads(content)
            return parsed_content

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            error_message = f"Failed to parse LLM response as JSON ({purpose}): {e}"
            logging.error(error_message)
            raise LLMResponseError(error_message) from e
        except openai.APIError as e:
            self._update_langfuse_error(e)
            error_message = f"OpenAI API error in call_with_structured_output_generic ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e
        except Exception as e:
            self._update_langfuse_error(e)
            error_message = f"Unexpected error in call_with_structured_output_generic ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="openai_json_output")
    async def call_with_json_output(self, purpose: str, prompt: str, model: str = None, temperature: float = None, **kwargs) -> dict:
        """
        Generic method for LLM calls expecting JSON output.

        This is a flexible method that doesn't require purpose-specific input mappings.
        Use for new features that need direct prompt-based calls.

        Args:
            purpose: Purpose identifier (for logging)
            prompt: The full prompt to send to the LLM
            model: Model to use (default from config)
            temperature: Temperature setting (default from config)

        Returns:
            Parsed JSON response as dict
        """
        try:
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            client = self._get_openai_client()

            logging.info(f"[{purpose}] Making JSON output call with model={model}")

            messages = [{"role": MessageRole.USER, "content": prompt}]

            self._update_langfuse_input(model, messages, purpose, temperature)

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            logging.debug(f"[{purpose}] Raw response: {content[:500]}...")

            self._update_langfuse_output(content, response.usage)

            parsed_content = json.loads(content)
            return parsed_content

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            error_message = f"Failed to parse LLM response as JSON ({purpose}): {e}"
            logging.error(error_message)
            raise LLMResponseError(error_message) from e
        except openai.APIError as e:
            self._update_langfuse_error(e)
            error_message = f"OpenAI API error in call_with_json_output ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e
        except Exception as e:
            self._update_langfuse_error(e)
            error_message = f"Unexpected error in call_with_json_output ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="openai_simple")
    async def call_simple(self, purpose: str, prompt: str, model: str = None, temperature: float = None, **kwargs) -> str:
        """
        Generic method for simple text LLM calls.

        Use for straightforward text generation without structured output.

        Args:
            purpose: Purpose identifier (for logging)
            prompt: The full prompt to send to the LLM
            model: Model to use (default from config - mini model for cost efficiency)
            temperature: Temperature setting (default from config)

        Returns:
            Text response as string
        """
        try:
            settings = get_settings()
            model = model or settings.llm.default_model_mini
            temperature = temperature if temperature is not None else settings.llm.temperature_simple

            client = self._get_openai_client()

            logging.info(f"[{purpose}] Making simple call with model={model}")

            messages = [{"role": MessageRole.USER, "content": prompt}]

            self._update_langfuse_input(model, messages, purpose, temperature)

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )

            content = response.choices[0].message.content
            logging.debug(f"[{purpose}] Response: {content[:200]}...")

            self._update_langfuse_output(content, response.usage)

            return content

        except openai.APIError as e:
            self._update_langfuse_error(e)
            error_message = f"OpenAI API error in call_simple ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e
        except Exception as e:
            self._update_langfuse_error(e)
            error_message = f"Unexpected error in call_simple ({purpose}): {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_input_by_purpose(self, purpose: str, call_type: str, **kwargs) -> dict[str, Any]:
        try:
            if purpose not in self.INPUT_PURPOSE_MAP[call_type]:
                raise ValidationError(f"Purpose '{purpose}' not found in INPUT_PURPOSE_MAP")

            function_to_call = self.INPUT_PURPOSE_MAP[call_type][purpose]
            purpose_specific_input = function_to_call(**kwargs)

            return purpose_specific_input

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error in _get_input_by_purpose method: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_input_for_translate_whatsapp_group_messages(self, **kwargs) -> Any:
        try:
            translate_from = kwargs.get(LlmInputKeys.TRANSLATE_FROM, DEFAULT_LANGUAGE)
            translate_to = kwargs.get(LlmInputKeys.TRANSLATE_TO, DEFAULT_HTML_LANGUAGE)

            content_batch = kwargs.get(LlmInputKeys.CONTENT_BATCH)
            if not content_batch or not isinstance(content_batch, list):
                error_message = "content_batch is required when calling _get_input_for_translate_whatsapp_group_messages"
                logging.error(error_message)
                raise ValueError(error_message)

            system_prompt = TRANSLATE_MESSAGES_PROMPT.format(translate_from=translate_from, translate_to=translate_to)

            messages = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": json.dumps(content_batch, ensure_ascii=False, indent=4)}]

            settings = get_settings()
            return {
                "model": settings.llm.default_model,
                "messages": messages,
                "temperature": settings.llm.temperature_translation,
            }

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error while translating whatsapp group messages: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_input_for_separate_whatsapp_group_message_discussions(self, **kwargs) -> Any:
        try:
            messages = kwargs.get(LlmInputKeys.MESSAGES, [])
            if not messages or not isinstance(messages, list):
                raise ValueError("messages list is required when calling _get_input_for_separate_whatsapp_group_message_discussions")

            chat_name = kwargs.get(LlmInputKeys.CHAT_NAME)
            if not chat_name:
                raise ValueError("chat_name is required when calling _get_input_for_separate_whatsapp_group_message_discussions")

            from utils.validation import sanitize_chat_name_for_prompt
            chat_name = sanitize_chat_name_for_prompt(chat_name)

            system_prompt = SEPARATE_DISCUSSIONS_PROMPT.format(chat_name=chat_name)

            messages_prompt = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": json.dumps(messages, ensure_ascii=False)}]

            settings = get_settings()
            return {
                "model": settings.llm.default_model,
                "messages": messages_prompt,
                "temperature": settings.llm.temperature_discussion_separation,
            }

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error while separating WhatsApp group message discussions: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_input_for_translate_newsletter_summary(self, **kwargs) -> Any:
        try:
            input_to_translate = kwargs.get(LlmInputKeys.INPUT_TO_TRANSLATE)
            if not input_to_translate:
                raise ValueError("input_to_translate is required when calling _get_input_for_translate_newsletter_summary")

            desired_language_for_summary = kwargs.get(LlmInputKeys.DESIRED_LANGUAGE_FOR_SUMMARY)

            system_prompt = TRANSLATE_NEWSLETTER_PROMPT.format(desired_language=desired_language_for_summary)

            messages_prompt = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": f"Here is the technical newsletter summary to translate:\n\n{input_to_translate}. Maintain the requirements."}]

            settings = get_settings()
            return {
                "messages": messages_prompt,
                "model": settings.llm.default_model,
                "temperature": settings.llm.temperature_json,
            }

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error while translating newsletter summary: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e

    def _get_input_for_generate_content_wa_community_langtalks_newsletter(self, **kwargs) -> Any:
        try:
            separate_discussions = kwargs.get(LlmInputKeys.JSON_INPUT_TO_SUMMARIZE)
            if not separate_discussions:
                raise ValueError("json_input_to_summarize is required when calling _get_input_for_generate_content_wa_community_langtalks_newsletter")

            examples = kwargs.get(LlmInputKeys.EXAMPLES)
            if not examples:
                raise ValueError("examples is required when calling _get_input_for_generate_content_wa_community_langtalks_newsletter")

            settings = get_settings()
            model = kwargs.get(LlmInputKeys.MODEL, settings.llm.default_model)

            brief_mention_items = kwargs.get(LlmInputKeys.BRIEF_MENTION_ITEMS, [])

            if brief_mention_items:
                worth_mentioning_guidance = WORTH_MENTIONING_WITH_CANDIDATES.format(num_candidates=len(brief_mention_items), brief_mention_items=json.dumps(brief_mention_items, indent=2, ensure_ascii=False))
            else:
                worth_mentioning_guidance = WORTH_MENTIONING_WITHOUT_CANDIDATES

            system_prompt = LANGTALKS_NEWSLETTER_PROMPT.format(worth_mentioning_guidance=worth_mentioning_guidance)

            messages = [{"role": MessageRole.SYSTEM, "content": system_prompt}]

            for i, example in enumerate(examples):
                messages.append({"role": MessageRole.ASSISTANT, "content": f"Example {i+1}:\n\n{example}"})

            messages.append({"role": MessageRole.USER, "content": ("According to the requirements and instructions you were given, and inspired by the examples Please generate the LangTalks newsletter summary for the following discussions:\n\n" f"{json.dumps(separate_discussions, indent=2, ensure_ascii=False)}")})

            return {
                "model": model,
                "messages": messages,
                "temperature": settings.llm.temperature_json,
            }

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error while generating content for LangTalks newsletter: {e}"
            logging.error(error_message)
            raise LLMError(error_message) from e


# Backward compatibility alias
OpenaiCaller = OpenAIProvider
