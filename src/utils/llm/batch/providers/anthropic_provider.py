"""
Anthropic Batch API Provider

Implements the BatchAPIProvider interface for Anthropic's Message Batches API.
Provides 50% cost savings with 24-hour SLA.

Anthropic Batch API Flow:
1. Create batch with requests directly (no file upload needed)
2. Poll for processing_status == "ended"
3. Iterate results stream

Structured Output:
Uses tool_use to guarantee structured JSON output. The response_format
from BatchRequest (OpenAI-style json_schema) is converted to an Anthropic
tool definition with input_schema.
"""

import json
import logging
import os
import time
from datetime import datetime, UTC

from anthropic import Anthropic

from ..interface import BatchAPIProvider
from ..types import (
    BatchInfo,
    BatchRequest,
    BatchRequestResult,
    BatchResult,
    BatchStatus,
)
from constants import ANTHROPIC_LLM_PROVIDER, ANTHROPIC_TRANSLATION_TOOL_NAME, MessageRole

logger = logging.getLogger(__name__)


class AnthropicBatchProvider(BatchAPIProvider):
    """
    Anthropic Message Batches API implementation.

    Provides 50% cost savings compared to synchronous API calls.
    SLA is 24 hours but typically completes in minutes.
    """

    # Polling configuration
    INITIAL_POLL_INTERVAL_SECONDS = 30
    MAX_POLL_INTERVAL_SECONDS = 300  # 5 minutes cap
    BACKOFF_MULTIPLIER = 1.5

    # Status mapping from Anthropic processing_status to our generic status
    _STATUS_MAP = {
        "in_progress": BatchStatus.IN_PROGRESS,
        "ended": BatchStatus.COMPLETED,
        "canceling": BatchStatus.IN_PROGRESS,
    }

    def __init__(self, model: str | None = None, api_key: str | None = None):
        """
        Initialize the Anthropic batch provider.

        Args:
            model: Default model to use (falls back to config default)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        from config import get_settings

        self._model = model or get_settings().llm.anthropic_default_model
        self._api_key = api_key
        self._client: Anthropic | None = None

    @property
    def provider_name(self) -> str:
        return ANTHROPIC_LLM_PROVIDER

    @property
    def default_model(self) -> str:
        return self._model

    def _get_client(self) -> Anthropic:
        """Get or create Anthropic client."""
        if self._client is None:
            api_key = self._api_key or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not found. Set it in environment or pass to constructor.")
            self._client = Anthropic(api_key=api_key)
        return self._client

    def _response_format_to_tool(self, response_format: dict) -> dict:
        """
        Convert OpenAI-style response_format to an Anthropic tool definition.

        The BatchTranslator passes response_format with type "json_schema".
        We extract the schema and wrap it as an Anthropic tool with input_schema.

        Args:
            response_format: OpenAI-style response format dict

        Returns:
            Anthropic tool definition dict
        """
        json_schema_config = response_format.get("json_schema", {})
        schema = json_schema_config.get("schema", {})
        tool_name = ANTHROPIC_TRANSLATION_TOOL_NAME

        # Strip additionalProperties from schema since Anthropic doesn't support it
        cleaned_schema = self._clean_schema(schema)

        return {
            "name": tool_name,
            "description": "Return the translated messages in the required JSON structure.",
            "input_schema": cleaned_schema,
        }

    def _clean_schema(self, schema: dict) -> dict:
        """
        Clean a JSON schema for Anthropic tool_use compatibility.

        Removes 'additionalProperties' and 'strict' fields that Anthropic
        doesn't support in tool input_schema.

        Args:
            schema: JSON schema dict

        Returns:
            Cleaned schema dict
        """
        cleaned = {}
        for key, value in schema.items():
            if key in ("additionalProperties", "strict"):
                continue
            if isinstance(value, dict):
                cleaned[key] = self._clean_schema(value)
            elif isinstance(value, list):
                cleaned[key] = [self._clean_schema(item) if isinstance(item, dict) else item for item in value]
            else:
                cleaned[key] = value
        return cleaned

    def _convert_request(self, request: BatchRequest) -> dict:
        """
        Convert a generic BatchRequest to Anthropic batch request format.

        Handles:
        - Extracting system messages from the messages list
        - Converting response_format to tool_use
        - Building the Anthropic-specific params structure

        Args:
            request: Generic batch request

        Returns:
            Anthropic batch request dict
        """
        # Separate system messages from user/assistant messages
        system_content = None
        non_system_messages = []

        for msg in request.messages:
            if msg.get("role") == MessageRole.SYSTEM:
                system_content = msg.get("content", "")
            else:
                non_system_messages.append(msg)

        params = {
            "model": request.model or self._model,
            "max_tokens": self._get_max_tokens(),
            "messages": non_system_messages,
            "temperature": request.temperature,
        }

        if system_content:
            params["system"] = system_content

        # Convert response_format to tool_use for structured output
        if request.response_format and request.response_format.get("type") == "json_schema":
            tool_def = self._response_format_to_tool(request.response_format)
            params["tools"] = [tool_def]
            params["tool_choice"] = {
                "type": "tool",
                "name": tool_def["name"],
            }

        return {
            "custom_id": request.custom_id,
            "params": params,
        }

    def _get_max_tokens(self) -> int:
        """Get max tokens from config."""
        try:
            from config import get_settings

            return get_settings().llm.anthropic_max_tokens
        except Exception:
            return 16384

    def submit_batch(self, requests: list[BatchRequest], metadata: dict | None = None) -> BatchInfo:
        """Submit a batch of requests to Anthropic."""
        if not requests:
            raise ValueError("Cannot submit empty batch")

        client = self._get_client()

        try:
            anthropic_requests = [self._convert_request(r) for r in requests]

            batch = client.messages.batches.create(requests=anthropic_requests)

            logger.info(f"Submitted Anthropic batch {batch.id} with {len(requests)} requests")

            return BatchInfo(
                batch_id=batch.id,
                status=BatchStatus.IN_PROGRESS,
                total_requests=len(requests),
                created_at=datetime.now(UTC),
            )

        except Exception as e:
            raise RuntimeError(f"Failed to submit Anthropic batch: {e}") from e

    def get_status(self, batch_id: str) -> BatchStatus:
        """Get current status of a batch."""
        client = self._get_client()

        try:
            batch = client.messages.batches.retrieve(batch_id)
            return self._STATUS_MAP.get(batch.processing_status, BatchStatus.IN_PROGRESS)

        except Exception as e:
            raise RuntimeError(f"Failed to get Anthropic batch status: {e}") from e

    def _parse_result(self, entry) -> BatchRequestResult:
        """
        Parse a single batch result entry into BatchRequestResult.

        Handles succeeded, errored, expired, and canceled result types.
        For succeeded results with tool_use, extracts the tool input as JSON string.

        Args:
            entry: Anthropic batch result entry

        Returns:
            Parsed BatchRequestResult
        """
        custom_id = entry.custom_id
        result = entry.result

        if result.type == "succeeded":
            message = result.message

            # Extract tool_use content (structured output)
            for content_block in message.content:
                if content_block.type == "tool_use":
                    return BatchRequestResult(
                        custom_id=custom_id,
                        success=True,
                        content=json.dumps(content_block.input, ensure_ascii=False),
                        usage={
                            "input_tokens": message.usage.input_tokens,
                            "output_tokens": message.usage.output_tokens,
                        },
                    )

            # Fallback: extract text content if no tool_use found
            text_parts = [block.text for block in message.content if hasattr(block, "text")]
            if text_parts:
                return BatchRequestResult(
                    custom_id=custom_id,
                    success=True,
                    content=text_parts[0],
                    usage={
                        "input_tokens": message.usage.input_tokens,
                        "output_tokens": message.usage.output_tokens,
                    },
                )

            return BatchRequestResult(
                custom_id=custom_id,
                success=False,
                error="No tool_use or text content in response",
            )

        if result.type == "errored":
            error_msg = str(result.error) if hasattr(result, "error") else "Unknown error"
            return BatchRequestResult(
                custom_id=custom_id,
                success=False,
                error=error_msg,
            )

        # expired or canceled
        return BatchRequestResult(
            custom_id=custom_id,
            success=False,
            error=f"Request {result.type}",
        )

    def get_results(self, batch_id: str) -> BatchResult:
        """Get results for a completed batch."""
        client = self._get_client()

        try:
            batch = client.messages.batches.retrieve(batch_id)

            if batch.processing_status != "ended":
                raise RuntimeError(f"Batch {batch_id} is not completed (status: {batch.processing_status})")

            # Iterate results stream
            results = []
            result_stream = client.messages.batches.results(batch_id)
            for entry in result_stream:
                results.append(self._parse_result(entry))

            completed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            return BatchResult(
                batch_id=batch_id,
                status=BatchStatus.COMPLETED,
                results=results,
                total_requests=len(results),
                completed_requests=completed,
                failed_requests=failed,
            )

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to get Anthropic batch results: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch."""
        client = self._get_client()

        try:
            client.messages.batches.cancel(batch_id)
            logger.info(f"Cancelled Anthropic batch: {batch_id}")
            return True

        except Exception as e:
            raise RuntimeError(f"Failed to cancel Anthropic batch: {e}") from e

    def execute_batch(self, requests: list[BatchRequest], timeout_minutes: int = 120, poll_interval_seconds: int = 30, metadata: dict | None = None) -> BatchResult:
        """
        Execute a batch synchronously (submit, poll, return results).

        Blocks until completion or timeout.
        """
        # Submit batch
        batch_info = self.submit_batch(requests, metadata)
        batch_id = batch_info.batch_id

        logger.info(f"Submitted Anthropic batch {batch_id} with {len(requests)} requests. " f"Polling (timeout: {timeout_minutes} minutes)...")

        # Poll for completion
        client = self._get_client()
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        poll_interval = poll_interval_seconds

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Anthropic batch {batch_id} did not complete within {timeout_minutes} minutes. " f"Check status manually with batch_id={batch_id}")

            try:
                batch = client.messages.batches.retrieve(batch_id)
                status = batch.processing_status

                # Log progress from request_counts
                counts = batch.request_counts
                logger.info(f"Anthropic batch {batch_id} status: {status} " f"(succeeded: {counts.succeeded}/{counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired}, " f"errored: {counts.errored})")

                if status == "ended":
                    return self.get_results(batch_id)

                # Still in progress - sleep and retry
                time.sleep(poll_interval)

                # Exponential backoff
                poll_interval = min(poll_interval * self.BACKOFF_MULTIPLIER, self.MAX_POLL_INTERVAL_SECONDS)

            except RuntimeError:
                raise
            except TimeoutError:
                raise
            except Exception as e:
                logger.warning(f"Error polling Anthropic batch {batch_id}: {e}")
                time.sleep(poll_interval)
