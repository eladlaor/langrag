"""
Gemini Batch API Provider

Implements the BatchAPIProvider interface for Google Gemini's Batch Prediction API.
Provides 50% cost savings with 24-hour SLA.

Gemini Batch API Flow:
1. Create batch with inline requests
2. Poll for state "JOB_STATE_SUCCEEDED"
3. Retrieve results from inlined responses or output file
"""

import logging
import os
import time
from datetime import datetime, UTC

from ..interface import BatchAPIProvider
from ..types import (
    BatchInfo,
    BatchRequest,
    BatchRequestResult,
    BatchResult,
    BatchStatus,
)
from constants import GEMINI_LLM_PROVIDER, MessageRole

logger = logging.getLogger(__name__)


class GeminiBatchProvider(BatchAPIProvider):
    """
    Google Gemini Batch Prediction API implementation.

    Provides 50% cost savings compared to synchronous API calls.
    SLA is 24 hours but typically completes faster.
    """

    # Polling configuration
    INITIAL_POLL_INTERVAL_SECONDS = 30
    MAX_POLL_INTERVAL_SECONDS = 300
    BACKOFF_MULTIPLIER = 1.5

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self._model = model or "gemini-2.5-flash"
        self._api_key = api_key
        self._client = None

    @property
    def provider_name(self) -> str:
        return GEMINI_LLM_PROVIDER

    @property
    def default_model(self) -> str:
        return self._model

    def _get_client(self):
        """Get or create Gemini client."""
        if self._client is None:
            api_key = self._api_key or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY not found. Set it in environment or pass to constructor.")
            from google import genai

            self._client = genai.Client(api_key=api_key)
        return self._client

    def _convert_messages_to_contents(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Convert OpenAI-style messages to Gemini contents."""
        system_instruction = None
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == MessageRole.SYSTEM:
                system_instruction = content
            elif role == MessageRole.ASSISTANT:
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})
        return system_instruction, contents

    def _convert_request(self, request: BatchRequest) -> dict:
        """Convert a generic BatchRequest to Gemini batch request format."""
        system_instruction, contents = self._convert_messages_to_contents(request.messages)

        config = {
            "temperature": request.temperature,
        }

        if request.response_format and request.response_format.get("type") == "json_schema":
            config["response_mime_type"] = "application/json"
            json_schema = request.response_format.get("json_schema", {}).get("schema")
            if json_schema:
                config["response_schema"] = json_schema

        if system_instruction:
            config["system_instruction"] = system_instruction

        return {
            "key": request.custom_id,
            "request": {
                "model": request.model or self._model,
                "contents": contents,
                "config": config,
            },
        }

    def submit_batch(self, requests: list[BatchRequest], metadata: dict | None = None) -> BatchInfo:
        """Submit a batch of requests to Gemini."""
        if not requests:
            raise ValueError("Cannot submit empty batch")

        client = self._get_client()

        try:
            from google.genai import types

            gemini_requests = []
            for req in requests:
                system_instruction, contents = self._convert_messages_to_contents(req.messages)

                config_kwargs = {"temperature": req.temperature}
                if req.response_format and req.response_format.get("type") == "json_schema":
                    config_kwargs["response_mime_type"] = "application/json"
                    schema = req.response_format.get("json_schema", {}).get("schema")
                    if schema:
                        config_kwargs["response_schema"] = schema
                if system_instruction:
                    config_kwargs["system_instruction"] = system_instruction

                gemini_requests.append(
                    types.BatchJobSource(
                        key=req.custom_id,
                        request=types.GenerateContentRequest(
                            model=req.model or self._model,
                            contents=contents,
                            config=types.GenerateContentConfig(**config_kwargs),
                        ),
                    )
                )

            batch = client.batches.create(
                model=self._model,
                src=gemini_requests,
            )

            batch_id = batch.name
            logger.info(f"Submitted Gemini batch {batch_id} with {len(requests)} requests")

            return BatchInfo(
                batch_id=batch_id,
                status=BatchStatus.IN_PROGRESS,
                total_requests=len(requests),
                created_at=datetime.now(UTC),
            )

        except Exception as e:
            raise RuntimeError(f"Failed to submit Gemini batch: {e}") from e

    def get_status(self, batch_id: str) -> BatchStatus:
        """Get current status of a batch."""
        client = self._get_client()

        try:
            batch = client.batches.get(name=batch_id)
            state = getattr(batch, "state", None)
            state_name = state.name if state else "UNKNOWN"

            status_map = {
                "JOB_STATE_SUCCEEDED": BatchStatus.COMPLETED,
                "JOB_STATE_FAILED": BatchStatus.FAILED,
                "JOB_STATE_CANCELLED": BatchStatus.CANCELLED,
                "JOB_STATE_PENDING": BatchStatus.IN_PROGRESS,
                "JOB_STATE_RUNNING": BatchStatus.IN_PROGRESS,
            }
            return status_map.get(state_name, BatchStatus.IN_PROGRESS)

        except Exception as e:
            raise RuntimeError(f"Failed to get Gemini batch status: {e}") from e

    def get_results(self, batch_id: str) -> BatchResult:
        """Get results for a completed batch."""
        client = self._get_client()

        try:
            batch = client.batches.get(name=batch_id)

            # Get results from dest (inlined responses)
            results = []
            if hasattr(batch, "dest") and hasattr(batch.dest, "inlined_responses"):
                for entry in batch.dest.inlined_responses:
                    key = getattr(entry, "key", "unknown")
                    response = getattr(entry, "response", None)

                    if response and hasattr(response, "candidates") and response.candidates:
                        text = response.candidates[0].content.parts[0].text if response.candidates[0].content.parts else ""
                        results.append(
                            BatchRequestResult(
                                custom_id=key,
                                success=True,
                                content=text,
                            )
                        )
                    else:
                        results.append(
                            BatchRequestResult(
                                custom_id=key,
                                success=False,
                                error="No candidates in Gemini response",
                            )
                        )

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

        except Exception as e:
            raise RuntimeError(f"Failed to get Gemini batch results: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch."""
        client = self._get_client()

        try:
            client.batches.cancel(name=batch_id)
            logger.info(f"Cancelled Gemini batch: {batch_id}")
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to cancel Gemini batch: {e}") from e

    def execute_batch(self, requests: list[BatchRequest], timeout_minutes: int = 120, poll_interval_seconds: int = 30, metadata: dict | None = None) -> BatchResult:
        """Execute a batch synchronously (submit, poll, return results)."""
        batch_info = self.submit_batch(requests, metadata)
        batch_id = batch_info.batch_id

        logger.info(f"Submitted Gemini batch {batch_id} with {len(requests)} requests. " f"Polling (timeout: {timeout_minutes} minutes)...")

        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        poll_interval = poll_interval_seconds

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Gemini batch {batch_id} did not complete within {timeout_minutes} minutes.")

            try:
                status = self.get_status(batch_id)
                logger.info(f"Gemini batch {batch_id} status: {status}")

                if status == BatchStatus.COMPLETED:
                    return self.get_results(batch_id)

                if status in (BatchStatus.FAILED, BatchStatus.CANCELLED):
                    raise RuntimeError(f"Gemini batch {batch_id} ended with status: {status}")

                time.sleep(poll_interval)
                poll_interval = min(poll_interval * self.BACKOFF_MULTIPLIER, self.MAX_POLL_INTERVAL_SECONDS)

            except (RuntimeError, TimeoutError):
                raise
            except Exception as e:
                logger.warning(f"Error polling Gemini batch {batch_id}: {e}")
                time.sleep(poll_interval)
