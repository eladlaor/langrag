"""
Gemini LLM Provider

Implementation of the LLM provider interface for Google Gemini models.
Uses the google-genai SDK for all calls.
Instrumented with Langfuse for tracing and cost tracking.
"""

import json
import logging
import os
from typing import Any
from collections.abc import Callable

from pydantic import Field

from config import get_settings
from utils.llm.retry import with_retry
from constants import (
    LlmInputPurposes,
    LLMCallType,
    DEFAULT_LANGUAGE,
    DEFAULT_HTML_LANGUAGE,
    MessageRole,
)
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

logger = logging.getLogger(__name__)


def _messages_to_gemini_contents(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Convert OpenAI-style messages to Gemini contents format.

    Returns:
        Tuple of (system_instruction, contents)
    """
    system_instruction = None
    contents = []

    for msg in messages:
        role = msg.get("role", MessageRole.USER)
        content = msg.get("content", "")

        if role == MessageRole.SYSTEM:
            system_instruction = content
        elif role == MessageRole.ASSISTANT:
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            contents.append({"role": "user", "parts": [{"text": content}]})

    return system_instruction, contents


def _pydantic_to_json_schema(response_schema: Any) -> dict:
    """Convert Pydantic model to JSON schema dict."""
    if hasattr(response_schema, "model_json_schema"):
        return response_schema.model_json_schema()
    elif hasattr(response_schema, "schema"):
        return response_schema.schema()
    return response_schema


class GeminiProvider(LLMProviderInterface):
    """
    Google Gemini LLM provider implementation.

    Uses the google-genai SDK for structured output, JSON output, and text generation.
    """

    INPUT_PURPOSE_MAP: dict[str, dict[str, Callable[..., dict[str, Any]]]] = Field(default_factory=dict)
    gemini_client: Any | None = Field(default=None)

    def __init__(self, **kwargs: Any) -> None:
        try:
            super().__init__(**kwargs)
            self.gemini_client = None
            self.INPUT_PURPOSE_MAP = {
                LLMCallType.STRUCTURED_OUTPUT: {
                    LlmInputPurposes.TRANSLATE_WHATSAPP_GROUP_MESSAGES: self._get_input_for_translate_whatsapp_group_messages,
                    LlmInputPurposes.SEPARATE_DISCUSSIONS: self._get_input_for_separate_whatsapp_group_message_discussions,
                    LlmInputPurposes.TRANSLATE_SUMMARY: self._get_input_for_translate_newsletter_summary,
                    LlmInputPurposes.GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER: self._get_input_for_generate_content_wa_community_langtalks_newsletter,
                }
            }
        except Exception as e:
            error_message = f"Error while initializing Gemini provider: {e}"
            logger.error(error_message)
            raise LLMError(error_message) from e

    def _get_gemini_client(self):
        try:
            if not self.gemini_client:
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ConfigurationError("GEMINI_API_KEY not found in environment variables. " "Set it in .env or as an environment variable.")
                from google import genai

                self.gemini_client = genai.Client(api_key=api_key)
            return self.gemini_client
        except ConfigurationError:
            raise
        except Exception as e:
            error_message = f"Error while initializing Gemini client: {e}"
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

    def _update_langfuse_output(self, content: str, usage: Any = None) -> None:
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            usage_dict = {}
            if usage:
                usage_dict = {
                    "input": getattr(usage, "prompt_token_count", 0) or getattr(usage, "prompt_tokens", 0),
                    "output": getattr(usage, "candidates_token_count", 0) or getattr(usage, "completion_tokens", 0),
                    "total": getattr(usage, "total_token_count", 0) or 0,
                    "unit": "TOKENS",
                }
            langfuse_context.update_current_observation(output=content, usage=usage_dict)
        except Exception as trace_err:
            logging.debug(f"Failed to update Langfuse observation output: {trace_err}")

    def _update_langfuse_error(self, error: Exception) -> None:
        if not (LANGFUSE_AVAILABLE and langfuse_context and is_langfuse_enabled()):
            return
        try:
            langfuse_context.update_current_observation(level="ERROR", status_message=str(error))
        except Exception:
            pass

    # =========================================================================
    # Public API methods
    # =========================================================================

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="gemini_structured_output")
    async def call_with_structured_output(self, purpose: str, response_schema: Any, **kwargs) -> Any:
        try:
            client = self._get_gemini_client()
            purpose_specific_input = self._get_input_by_purpose(purpose, "structured_output", **kwargs)

            settings = get_settings()
            model = purpose_specific_input.get("model", settings.llm.default_model)
            temperature = purpose_specific_input.get("temperature", settings.llm.temperature_json)
            messages = purpose_specific_input.get("messages", [])

            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            system_instruction, contents = _messages_to_gemini_contents(messages)
            schema = _pydantic_to_json_schema(response_schema)

            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=schema,
            )
            if system_instruction:
                config.system_instruction = system_instruction

            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            content = response.text
            self._update_langfuse_output(content, getattr(response, "usage_metadata", None))
            return json.loads(content)

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Gemini response as JSON: {e}") from e
        except (ConfigurationError, ValidationError):
            raise
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in Gemini call_with_structured_output: {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="gemini_structured_output_generic")
    async def call_with_structured_output_generic(self, messages: list[dict], response_schema: type, purpose: str = "generic", model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        try:
            client = self._get_gemini_client()
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            logger.info(f"[{purpose}] Making Gemini structured output call with model={model}")
            self._update_langfuse_input(model, messages, purpose, temperature, response_schema)

            system_instruction, contents = _messages_to_gemini_contents(messages)
            schema = _pydantic_to_json_schema(response_schema)

            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=schema,
            )
            if system_instruction:
                config.system_instruction = system_instruction

            response = await client.aio.models.generate_content(model=model, contents=contents, config=config)
            content = response.text
            self._update_langfuse_output(content, getattr(response, "usage_metadata", None))
            return json.loads(content)

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Gemini response as JSON ({purpose}): {e}") from e
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in Gemini call_with_structured_output_generic ({purpose}): {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="gemini_json_output")
    async def call_with_json_output(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> dict:
        try:
            settings = get_settings()
            model = model or settings.llm.default_model
            temperature = temperature if temperature is not None else settings.llm.temperature_json

            client = self._get_gemini_client()
            logger.info(f"[{purpose}] Making Gemini JSON output call with model={model}")

            messages = [{"role": MessageRole.USER, "content": prompt}]
            self._update_langfuse_input(model, messages, purpose, temperature)

            system_instruction, contents = _messages_to_gemini_contents(messages)

            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
            )
            if system_instruction:
                config.system_instruction = system_instruction

            response = await client.aio.models.generate_content(model=model, contents=contents, config=config)
            content = response.text
            self._update_langfuse_output(content, getattr(response, "usage_metadata", None))
            return json.loads(content)

        except json.JSONDecodeError as e:
            self._update_langfuse_error(e)
            raise LLMResponseError(f"Failed to parse Gemini response as JSON ({purpose}): {e}") from e
        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in Gemini call_with_json_output ({purpose}): {e}") from e

    @with_retry(max_retries=3, base_delay=1.0)
    @observe(as_type="generation", name="gemini_simple")
    async def call_simple(self, purpose: str, prompt: str, model: str | None = None, temperature: float | None = None, **kwargs) -> str:
        try:
            settings = get_settings()
            model = model or settings.llm.default_model_mini
            temperature = temperature if temperature is not None else settings.llm.temperature_simple

            client = self._get_gemini_client()
            logger.info(f"[{purpose}] Making Gemini simple call with model={model}")

            messages = [{"role": MessageRole.USER, "content": prompt}]
            self._update_langfuse_input(model, messages, purpose, temperature)

            system_instruction, contents = _messages_to_gemini_contents(messages)

            from google.genai import types

            config = types.GenerateContentConfig(temperature=temperature)
            if system_instruction:
                config.system_instruction = system_instruction

            response = await client.aio.models.generate_content(model=model, contents=contents, config=config)
            content = response.text
            self._update_langfuse_output(content, getattr(response, "usage_metadata", None))
            return content

        except Exception as e:
            self._update_langfuse_error(e)
            raise LLMError(f"Unexpected error in Gemini call_simple ({purpose}): {e}") from e

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

    # =========================================================================
    # Purpose-specific input builders
    # =========================================================================

    def _get_input_for_translate_whatsapp_group_messages(self, **kwargs) -> Any:
        translate_from = kwargs.get(LlmInputKeys.TRANSLATE_FROM, DEFAULT_LANGUAGE)
        translate_to = kwargs.get(LlmInputKeys.TRANSLATE_TO, DEFAULT_HTML_LANGUAGE)
        content_batch = kwargs.get(LlmInputKeys.CONTENT_BATCH)
        if not content_batch or not isinstance(content_batch, list):
            raise ValueError("content_batch is required")
        system_prompt = TRANSLATE_MESSAGES_PROMPT.format(translate_from=translate_from, translate_to=translate_to)
        messages = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": json.dumps(content_batch, ensure_ascii=False, indent=4)}]
        settings = get_settings()
        return {"model": settings.llm.default_model, "messages": messages, "temperature": settings.llm.temperature_translation}

    def _get_input_for_separate_whatsapp_group_message_discussions(self, **kwargs) -> Any:
        messages = kwargs.get(LlmInputKeys.MESSAGES, [])
        if not messages or not isinstance(messages, list):
            raise ValueError("messages list is required")
        chat_name = kwargs.get(LlmInputKeys.CHAT_NAME)
        if not chat_name:
            raise ValueError("chat_name is required")
        from utils.validation import sanitize_chat_name_for_prompt
        chat_name = sanitize_chat_name_for_prompt(chat_name)
        system_prompt = SEPARATE_DISCUSSIONS_PROMPT.format(chat_name=chat_name)
        messages_prompt = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": json.dumps(messages, ensure_ascii=False)}]
        settings = get_settings()
        return {"model": settings.llm.default_model, "messages": messages_prompt, "temperature": settings.llm.temperature_discussion_separation}

    def _get_input_for_translate_newsletter_summary(self, **kwargs) -> Any:
        input_to_translate = kwargs.get(LlmInputKeys.INPUT_TO_TRANSLATE)
        if not input_to_translate:
            raise ValueError("input_to_translate is required")
        desired_language_for_summary = kwargs.get(LlmInputKeys.DESIRED_LANGUAGE_FOR_SUMMARY)
        system_prompt = TRANSLATE_NEWSLETTER_PROMPT.format(desired_language=desired_language_for_summary)
        messages_prompt = [{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": f"Here is the technical newsletter summary to translate:\n\n{input_to_translate}. Maintain the requirements."}]
        settings = get_settings()
        return {"messages": messages_prompt, "model": settings.llm.default_model, "temperature": settings.llm.temperature_json}

    def _get_input_for_generate_content_wa_community_langtalks_newsletter(self, **kwargs) -> Any:
        separate_discussions = kwargs.get(LlmInputKeys.JSON_INPUT_TO_SUMMARIZE)
        if not separate_discussions:
            raise ValueError("json_input_to_summarize is required")
        examples = kwargs.get(LlmInputKeys.EXAMPLES)
        if not examples:
            raise ValueError("examples is required")
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
        return {"model": model, "messages": messages, "temperature": settings.llm.temperature_json}
