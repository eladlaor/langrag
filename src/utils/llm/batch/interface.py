"""
Batch API Provider Interface

Defines the Protocol that all batch API providers must implement.
Uses Python's Protocol for structural subtyping (duck typing with type hints).
"""

from typing import Protocol, runtime_checkable

from .types import BatchInfo, BatchRequest, BatchResult, BatchStatus


@runtime_checkable
class BatchAPIProvider(Protocol):
    """
    Protocol for batch API providers.

    All batch API implementations (OpenAI, Anthropic, Gemini) must
    implement this interface to be used interchangeably.

    The batch API flow is:
    1. submit_batch() - Submit requests and get batch_id
    2. get_status() - Poll for completion
    3. get_results() - Retrieve results when completed

    Or use the convenience method:
    - execute_batch() - Submit, poll, and return results (blocking)

    Cost Savings:
    - OpenAI: 50% discount
    - Anthropic: 50% discount (stacks with prompt caching)
    - Gemini: 50% discount

    SLA: All providers have ~24 hour completion window.
    """

    @property
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'anthropic', 'gemini')."""
        ...

    @property
    def default_model(self) -> str:
        """Return the default model for this provider."""
        ...

    def submit_batch(self, requests: list[BatchRequest], metadata: dict | None = None) -> BatchInfo:
        """
        Submit a batch of requests.

        Args:
            requests: List of BatchRequest objects
            metadata: Optional metadata for the batch

        Returns:
            BatchInfo with batch_id for tracking

        Raises:
            RuntimeError: If submission fails
        """
        ...

    def get_status(self, batch_id: str) -> BatchStatus:
        """
        Get current status of a batch.

        Args:
            batch_id: The batch identifier from submit_batch()

        Returns:
            Current BatchStatus

        Raises:
            RuntimeError: If status check fails
        """
        ...

    def get_results(self, batch_id: str) -> BatchResult:
        """
        Get results for a completed batch.

        Should only be called when status is COMPLETED.

        Args:
            batch_id: The batch identifier

        Returns:
            BatchResult with all individual results

        Raises:
            RuntimeError: If batch not completed or retrieval fails
        """
        ...

    def cancel_batch(self, batch_id: str) -> bool:
        """
        Cancel a running batch.

        Args:
            batch_id: The batch identifier

        Returns:
            True if cancelled successfully

        Raises:
            RuntimeError: If cancellation fails
        """
        ...

    def execute_batch(self, requests: list[BatchRequest], timeout_minutes: int = 120, poll_interval_seconds: int = 30, metadata: dict | None = None) -> BatchResult:
        """
        Execute a batch synchronously (submit, poll, return results).

        Convenience method that handles the full batch lifecycle.
        Blocks until completion or timeout.

        Args:
            requests: List of BatchRequest objects
            timeout_minutes: Maximum time to wait for completion
            poll_interval_seconds: Initial polling interval (may use backoff)
            metadata: Optional metadata for the batch

        Returns:
            BatchResult with all results

        Raises:
            TimeoutError: If batch doesn't complete within timeout
            RuntimeError: If batch fails or is cancelled
        """
        ...
