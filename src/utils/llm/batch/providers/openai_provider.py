"""
OpenAI Batch API Provider

Implements the BatchAPIProvider interface for OpenAI's Batch API.
Provides 50% cost savings with 24-hour SLA.

OpenAI Batch API Flow:
1. Create JSONL file with requests
2. Upload file to Files API
3. Create batch job
4. Poll for completion
5. Download and parse results
"""

import json
import logging
import os
import tempfile
import time
from datetime import datetime, UTC

from openai import OpenAI

from ..interface import BatchAPIProvider
from ..types import (
    BatchInfo,
    BatchRequest,
    BatchRequestResult,
    BatchResult,
    BatchStatus,
)
from constants import DEFAULT_LLM_PROVIDER

logger = logging.getLogger(__name__)


class OpenAIBatchProvider(BatchAPIProvider):
    """
    OpenAI Batch API implementation.

    Provides 50% cost savings compared to synchronous API calls.
    SLA is 24 hours but typically completes in 10-60 minutes.
    """

    # Polling configuration
    INITIAL_POLL_INTERVAL_SECONDS = 30
    MAX_POLL_INTERVAL_SECONDS = 300  # 5 minutes cap
    BACKOFF_MULTIPLIER = 1.5

    # Status mapping from OpenAI to our generic status
    _STATUS_MAP = {
        "validating": BatchStatus.VALIDATING,
        "in_progress": BatchStatus.IN_PROGRESS,
        "completed": BatchStatus.COMPLETED,
        "failed": BatchStatus.FAILED,
        "cancelled": BatchStatus.CANCELLED,
        "expired": BatchStatus.EXPIRED,
        "finalizing": BatchStatus.IN_PROGRESS,  # Treat as in_progress
    }

    def __init__(self, model: str | None = None, api_key: str | None = None):
        """
        Initialize the OpenAI batch provider.

        Args:
            model: Default model to use (falls back to config default)
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        from config import get_settings

        self._model = model or get_settings().llm.openai_mini_model
        self._api_key = api_key
        self._client: OpenAI | None = None

    @property
    def provider_name(self) -> str:
        return DEFAULT_LLM_PROVIDER

    @property
    def default_model(self) -> str:
        return self._model

    def _get_client(self) -> OpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            api_key = self._api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not found. Set it in environment or pass to constructor.")
            self._client = OpenAI(api_key=api_key)
        return self._client

    def _create_jsonl_request(self, request: BatchRequest) -> dict:
        """
        Convert a BatchRequest to OpenAI JSONL format.

        Args:
            request: Generic batch request

        Returns:
            OpenAI batch API request dict
        """
        body = {
            "model": request.model or self._model,
            "messages": request.messages,
            "temperature": request.temperature,
        }

        # Add response format if specified
        if request.response_format:
            body["response_format"] = request.response_format

        # Add any additional metadata as extra body params
        for key, value in request.metadata.items():
            if key not in body:
                body[key] = value

        return {
            "custom_id": request.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _create_jsonl_file(self, requests: list[BatchRequest]) -> str:
        """
        Create JSONL file with all batch requests.

        Args:
            requests: List of BatchRequest objects

        Returns:
            Path to created JSONL file
        """
        fd, jsonl_path = tempfile.mkstemp(suffix=".jsonl", prefix="openai_batch_")

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for request in requests:
                    jsonl_request = self._create_jsonl_request(request)
                    f.write(json.dumps(jsonl_request, ensure_ascii=False) + "\n")

            logger.info(f"Created JSONL file with {len(requests)} requests: {jsonl_path}")
            return jsonl_path

        except Exception as e:
            if os.path.exists(jsonl_path):
                os.unlink(jsonl_path)
            raise RuntimeError(f"Failed to create JSONL file: {e}") from e

    def _upload_file(self, jsonl_path: str) -> str:
        """
        Upload JSONL file to OpenAI Files API.

        Args:
            jsonl_path: Path to JSONL file

        Returns:
            File ID
        """
        client = self._get_client()

        try:
            with open(jsonl_path, "rb") as f:
                file_response = client.files.create(file=f, purpose="batch")

            file_id = file_response.id
            logger.info(f"Uploaded batch file: {file_id}")
            return file_id

        except Exception as e:
            raise RuntimeError(f"Failed to upload batch file: {e}") from e

    def _create_batch_job(self, file_id: str, metadata: dict | None = None) -> str:
        """
        Create a batch job.

        Args:
            file_id: Uploaded file ID
            metadata: Optional metadata for the batch

        Returns:
            Batch ID
        """
        client = self._get_client()

        try:
            create_kwargs = {
                "input_file_id": file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            }

            if metadata:
                create_kwargs["metadata"] = metadata

            batch_response = client.batches.create(**create_kwargs)
            batch_id = batch_response.id
            logger.info(f"Created batch job: {batch_id}")
            return batch_id

        except Exception as e:
            raise RuntimeError(f"Failed to create batch job: {e}") from e

    def _map_status(self, openai_status: str) -> BatchStatus:
        """Map OpenAI status to generic BatchStatus."""
        return self._STATUS_MAP.get(openai_status, BatchStatus.IN_PROGRESS)

    def submit_batch(self, requests: list[BatchRequest], metadata: dict | None = None) -> BatchInfo:
        """Submit a batch of requests to OpenAI."""
        if not requests:
            raise ValueError("Cannot submit empty batch")

        jsonl_path = None
        try:
            # Create JSONL file
            jsonl_path = self._create_jsonl_file(requests)

            # Upload file
            file_id = self._upload_file(jsonl_path)

            # Create batch
            batch_id = self._create_batch_job(file_id, metadata)

            return BatchInfo(
                batch_id=batch_id,
                file_id=file_id,
                status=BatchStatus.VALIDATING,
                total_requests=len(requests),
                created_at=datetime.now(UTC),
            )

        finally:
            # Clean up temp file
            if jsonl_path and os.path.exists(jsonl_path):
                try:
                    os.unlink(jsonl_path)
                except Exception as e:
                    logger.warning(f"Failed to clean up temp file {jsonl_path}: {e}")

    def get_status(self, batch_id: str) -> BatchStatus:
        """Get current status of a batch."""
        client = self._get_client()

        try:
            batch = client.batches.retrieve(batch_id)
            return self._map_status(batch.status)

        except Exception as e:
            raise RuntimeError(f"Failed to get batch status: {e}") from e

    def _download_results(self, output_file_id: str) -> list[dict]:
        """
        Download and parse batch results.

        Args:
            output_file_id: Output file ID from completed batch

        Returns:
            List of result dicts
        """
        client = self._get_client()

        try:
            file_response = client.files.content(output_file_id)
            content = file_response.text

            results = []
            for line in content.strip().split("\n"):
                if line:
                    results.append(json.loads(line))

            logger.info(f"Downloaded {len(results)} batch results")
            return results

        except Exception as e:
            raise RuntimeError(f"Failed to download batch results: {e}") from e

    def _parse_result(self, raw_result: dict) -> BatchRequestResult:
        """
        Parse a single raw result into BatchRequestResult.

        Args:
            raw_result: Raw result dict from OpenAI

        Returns:
            Parsed BatchRequestResult
        """
        custom_id = raw_result.get("custom_id", "unknown")
        response = raw_result.get("response", {})

        # Check for errors
        if response.get("status_code") != 200:
            error_body = response.get("body", {})
            error_msg = error_body.get("error", {}).get("message", str(error_body))
            return BatchRequestResult(
                custom_id=custom_id,
                success=False,
                error=error_msg,
            )

        # Parse successful response
        body = response.get("body", {})
        choices = body.get("choices", [])

        if not choices:
            return BatchRequestResult(
                custom_id=custom_id,
                success=False,
                error="No choices in response",
            )

        content = choices[0].get("message", {}).get("content", "")
        usage = body.get("usage")

        return BatchRequestResult(
            custom_id=custom_id,
            success=True,
            content=content,
            usage=usage,
        )

    def get_results(self, batch_id: str) -> BatchResult:
        """Get results for a completed batch."""
        client = self._get_client()

        try:
            batch = client.batches.retrieve(batch_id)

            if batch.status != BatchStatus.COMPLETED:
                raise RuntimeError(f"Batch {batch_id} is not completed (status: {batch.status})")

            if not batch.output_file_id:
                raise RuntimeError(f"Batch {batch_id} has no output file")

            # Download and parse results
            raw_results = self._download_results(batch.output_file_id)
            results = [self._parse_result(r) for r in raw_results]

            completed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            return BatchResult(
                batch_id=batch_id,
                status=BatchStatus.COMPLETED,
                results=results,
                total_requests=batch.request_counts.total,
                completed_requests=completed,
                failed_requests=failed,
                metadata={
                    "output_file_id": batch.output_file_id,
                    "error_file_id": batch.error_file_id,
                },
            )

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to get batch results: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch."""
        client = self._get_client()

        try:
            client.batches.cancel(batch_id)
            logger.info(f"Cancelled batch: {batch_id}")
            return True

        except Exception as e:
            raise RuntimeError(f"Failed to cancel batch: {e}") from e

    def execute_batch(self, requests: list[BatchRequest], timeout_minutes: int = 120, poll_interval_seconds: int = 30, metadata: dict | None = None) -> BatchResult:
        """
        Execute a batch synchronously (submit, poll, return results).

        Blocks until completion or timeout.
        """
        # Submit batch
        batch_info = self.submit_batch(requests, metadata)
        batch_id = batch_info.batch_id

        logger.info(f"Submitted batch {batch_id} with {len(requests)} requests. " f"Polling (timeout: {timeout_minutes} minutes)...")

        # Poll for completion
        client = self._get_client()
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        poll_interval = poll_interval_seconds

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Batch {batch_id} did not complete within {timeout_minutes} minutes. " f"Check status manually with batch_id={batch_id}")

            try:
                batch = client.batches.retrieve(batch_id)
                status = batch.status

                logger.info(f"Batch {batch_id} status: {status} " f"(completed: {batch.request_counts.completed}/{batch.request_counts.total}, " f"failed: {batch.request_counts.failed})")

                if status == BatchStatus.COMPLETED:
                    return self.get_results(batch_id)

                if status in (BatchStatus.FAILED, BatchStatus.CANCELLED, BatchStatus.EXPIRED):
                    error_msg = f"Batch {batch_id} ended with status: {status}"
                    if hasattr(batch, "errors") and batch.errors:
                        error_msg += f" - Errors: {batch.errors}"
                    raise RuntimeError(error_msg)

                # Still in progress - sleep and retry
                time.sleep(poll_interval)

                # Exponential backoff
                poll_interval = min(poll_interval * self.BACKOFF_MULTIPLIER, self.MAX_POLL_INTERVAL_SECONDS)

            except RuntimeError:
                raise
            except TimeoutError:
                raise
            except Exception as e:
                logger.warning(f"Error polling batch {batch_id}: {e}")
                time.sleep(poll_interval)
