"""
Batch Translator

Translation-specific wrapper around the generic Batch API provider.
Handles message translation via batch API for 50% cost reduction.

This module is a domain-specific layer that:
1. Takes messages with content to translate
2. Converts them to batch requests with translation prompts
3. Uses the generic BatchAPIProvider for execution
4. Parses results back to translated messages

Usage:
    from utils.llm.batch import BatchTranslator

    translator = BatchTranslator()
    translated = translator.translate_messages_batch(
        all_messages=messages,
        translate_from="hebrew",
        translate_to="english",
        batch_size=50
    )
"""

import json
import logging

from config import get_settings
from constants import DEFAULT_LANGUAGE, DEFAULT_HTML_LANGUAGE, MessageRole, DEFAULT_LLM_PROVIDER, BATCH_TRANSLATE_CUSTOM_ID_PREFIX
from utils.llm.batch import BatchRequest, get_provider
from utils.llm.batch.interface import BatchAPIProvider
from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT

logger = logging.getLogger(__name__)


class BatchTranslator:
    """
    Translates messages using batch API.

    Domain-specific wrapper that handles translation logic while
    delegating batch execution to the generic BatchAPIProvider.
    """

    def __init__(self, model: str | None = None, provider_name: str = DEFAULT_LLM_PROVIDER):
        """
        Initialize the BatchTranslator.

        Args:
            model: Model to use for translation (default from config)
            provider_name: Batch API provider to use (default: openai)
        """
        settings = get_settings()
        self._model = model or settings.llm.default_model
        self._provider_name = provider_name
        self._provider: BatchAPIProvider | None = None

    def _get_provider(self) -> BatchAPIProvider:
        """Get or create batch API provider."""
        if self._provider is None:
            self._provider = get_provider(provider_name=self._provider_name, model=self._model)
        return self._provider

    def _get_response_format(self) -> dict:
        """
        Get the response format for translation requests.

        Uses json_schema format for structured output.
        """
        return {"type": "json_schema", "json_schema": {"name": "LlmResponseTranslateMessages", "strict": True, "schema": {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object", "properties": {"message": {"type": "string"}, "id": {"type": "string"}}, "required": ["message", "id"], "additionalProperties": False}}}, "required": ["messages"], "additionalProperties": False}}}

    def _create_translation_requests(self, all_messages: list[dict], batch_size: int, translate_from: str, translate_to: str) -> list[BatchRequest]:
        """
        Create batch requests for translation.

        Args:
            all_messages: All messages to translate
            batch_size: Messages per batch
            translate_from: Source language
            translate_to: Target language

        Returns:
            List of BatchRequest objects
        """
        total_messages = len(all_messages)
        total_batches = (total_messages + batch_size - 1) // batch_size
        requests = []

        system_prompt = TRANSLATE_MESSAGES_PROMPT.format(translate_from=translate_from, translate_to=translate_to)

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, total_messages)

            # Create content batch with id and content only
            content_batch = [{"id": msg["id"], "content": msg["content"]} for msg in all_messages[start_idx:end_idx]]

            request = BatchRequest(
                custom_id=f"{BATCH_TRANSLATE_CUSTOM_ID_PREFIX}{batch_idx}",
                messages=[{"role": MessageRole.SYSTEM, "content": system_prompt}, {"role": MessageRole.USER, "content": json.dumps(content_batch, ensure_ascii=False)}],
                model=self._model,
                temperature=0.3,
                response_format=self._get_response_format(),
            )
            requests.append(request)

        return requests

    def _parse_translation_results(self, batch_result, all_messages: list[dict], batch_size: int) -> list[dict]:
        """
        Parse batch results and merge translations back into messages.

        Args:
            batch_result: BatchResult from provider
            all_messages: Original messages
            batch_size: Messages per batch

        Returns:
            List of messages with translated content
        """
        # Create a copy of all messages
        translated_messages = [msg.copy() for msg in all_messages]

        # Build mapping from custom_id to batch index
        custom_id_to_batch_idx = {}
        for result in batch_result.results:
            custom_id = result.custom_id
            if custom_id.startswith(BATCH_TRANSLATE_CUSTOM_ID_PREFIX):
                batch_idx = int(custom_id.split("_")[-1])
                custom_id_to_batch_idx[custom_id] = batch_idx

        # Process each result
        for result in batch_result.results:
            custom_id = result.custom_id

            if not result.success:
                logger.warning(f"Translation batch {custom_id} failed: {result.error}")
                continue

            try:
                parsed = json.loads(result.content)
                translated_batch = parsed.get("messages", [])

                # Build id -> translated content map
                translation_map = {item["id"]: item["message"] for item in translated_batch if "id" in item and "message" in item}

                # Apply translations to the correct messages
                batch_idx = custom_id_to_batch_idx.get(custom_id)
                if batch_idx is not None:
                    start_idx = batch_idx * batch_size
                    end_idx = min(start_idx + batch_size, len(all_messages))

                    for i in range(start_idx, end_idx):
                        msg_id = all_messages[i]["id"]
                        if msg_id in translation_map:
                            translated_messages[i]["content"] = translation_map[msg_id]

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse response for {custom_id}: {e}")
                continue

        return translated_messages

    def translate_messages_batch(self, all_messages: list[dict], translate_from: str = DEFAULT_HTML_LANGUAGE, translate_to: str = DEFAULT_LANGUAGE, batch_size: int = 50, timeout_minutes: int = 120) -> tuple[list[dict], dict]:
        """
        Translate all messages using batch API.

        Args:
            all_messages: List of message dicts with 'id' and 'content' fields
            translate_from: Source language (default: DEFAULT_HTML_LANGUAGE)
            translate_to: Target language (default: DEFAULT_LANGUAGE)
            batch_size: Messages per batch request
            timeout_minutes: Maximum time to wait for batch completion

        Returns:
            Tuple of (translated_messages, batch_info)
            - translated_messages: List of messages with translated content
            - batch_info: Dict with batch_id, stats, and metadata

        Raises:
            RuntimeError: If any step fails
            TimeoutError: If batch doesn't complete in time
        """
        if not all_messages:
            logger.warning("No messages to translate")
            return [], {"batch_id": None, "message": "No messages to translate"}

        total_messages = len(all_messages)
        logger.info(f"Starting batch translation: {total_messages} messages, " f"batch_size={batch_size}, {translate_from} -> {translate_to}")

        # Create translation requests
        requests = self._create_translation_requests(all_messages=all_messages, batch_size=batch_size, translate_from=translate_from, translate_to=translate_to)

        # Execute batch
        provider = self._get_provider()
        batch_result = provider.execute_batch(
            requests=requests,
            timeout_minutes=timeout_minutes,
        )

        # Parse results
        translated_messages = self._parse_translation_results(batch_result=batch_result, all_messages=all_messages, batch_size=batch_size)

        batch_info = {
            "batch_id": batch_result.batch_id,
            "provider": provider.provider_name,
            "total_messages": total_messages,
            "total_batches": len(requests),
            "completed_requests": batch_result.completed_requests,
            "failed_requests": batch_result.failed_requests,
        }

        logger.info(f"Batch translation complete: {batch_info}")
        return translated_messages, batch_info


# Convenience function for direct use
def translate_with_batch_api(messages: list[dict], translate_from: str = DEFAULT_HTML_LANGUAGE, translate_to: str = DEFAULT_LANGUAGE, batch_size: int = 50, timeout_minutes: int = 120, model: str | None = None, provider_name: str = DEFAULT_LLM_PROVIDER) -> tuple[list[dict], dict]:
    """
    Convenience function to translate messages with batch API.

    See BatchTranslator.translate_messages_batch for full documentation.
    """
    translator = BatchTranslator(model=model, provider_name=provider_name)
    return translator.translate_messages_batch(all_messages=messages, translate_from=translate_from, translate_to=translate_to, batch_size=batch_size, timeout_minutes=timeout_minutes)
