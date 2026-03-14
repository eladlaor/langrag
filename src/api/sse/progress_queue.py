"""
Progress Queue for LangGraph Workflows

This module provides thread-safe progress tracking for LangGraph workflows,
enabling real-time Server-Sent Events (SSE) streaming to frontend clients.
"""

import asyncio
import logging
from typing import Any
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, UTC

from constants import PROGRESS_QUEUE_MAX_SIZE
from custom_types.sse_events import ProgressEvent, EventType

logger = logging.getLogger(__name__)

# Auto-cleanup stale queues after 2 hours with no subscribers
STALE_QUEUE_TIMEOUT_HOURS = 2


class ProgressQueue:
    """
    Thread-safe async queue for streaming progress events.

    This class manages a queue of progress events that can be safely
    accessed from multiple async tasks (graph nodes) and streamed to
    clients via Server-Sent Events.

    Features:
    - Thread-safe event emission from graph nodes
    - Async iteration for SSE streaming
    - Automatic cleanup and closure
    - Event buffering for late subscribers

    Example:
        # Create queue
        progress = ProgressQueue()

        # Emit events from nodes
        progress.emit("stage_progress", {"stage": "extract", "status": "in_progress"})

        # Stream to SSE endpoint
        async for event in progress.stream():
            yield f"data: {json.dumps(event.to_dict())}\n\n"

        # Cleanup
        progress.close()
    """

    def __init__(self, max_size: int | None = None):
        """
        Initialize progress queue.

        Args:
            max_size: Maximum number of events to buffer (prevents memory leaks)
        """
        max_size = max_size or PROGRESS_QUEUE_MAX_SIZE
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._closed = False
        self._subscribers = 0
        self._created_at = datetime.now(UTC)
        self._last_activity = datetime.now(UTC)
        logger.debug(f"ProgressQueue initialized with max_size={max_size}")

    def emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """
        Emit a progress event (non-blocking).

        This method is safe to call from sync or async contexts.
        Events are queued for streaming to subscribers.

        Args:
            event_type: Type of event being emitted
            data: Event payload data

        Example:
            progress.emit("stage_progress", {
                "chat_name": "LangTalks",
                "stage": "extract_messages",
                "status": "in_progress",
                "message": "Extracting 1000 messages..."
            })
        """
        if self._closed:
            logger.warning(f"Attempted to emit event to closed queue: {event_type}")
            return

        event = ProgressEvent(event_type=event_type, timestamp=datetime.now(UTC).isoformat(), data=data)

        try:
            # Use put_nowait to avoid blocking
            self._queue.put_nowait(event)
            self._last_activity = datetime.now(UTC)
            logger.debug(f"Emitted event: {event_type} - {data.get('message', '')}")
        except asyncio.QueueFull:
            logger.error(f"Progress queue full! Dropping event: {event_type}")

    async def stream(self) -> AsyncIterator[ProgressEvent]:
        """
        Stream events from the queue (async iterator).

        This method blocks until events are available or the queue is closed.
        Use in SSE endpoint to stream events to clients.

        Yields:
            ProgressEvent: Next available event from the queue

        Example:
            async for event in progress.stream():
                sse_data = f"data: {json.dumps(event.to_dict())}\n\n"
                yield sse_data
        """
        self._subscribers += 1
        logger.info(f"New subscriber to progress stream (total: {self._subscribers})")

        try:
            while not self._closed or not self._queue.empty():
                try:
                    # Wait for next event with timeout
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    yield event

                except TimeoutError:
                    # Send keepalive comment (prevents SSE timeout)
                    if not self._closed:
                        continue
                    else:
                        break

        finally:
            self._subscribers -= 1
            logger.info(f"Subscriber disconnected (remaining: {self._subscribers})")

    def close(self) -> None:
        """
        Close the queue and signal end of events.

        Call this after the workflow completes to gracefully
        shutdown any streaming connections.
        """
        if not self._closed:
            self._closed = True
            logger.info("ProgressQueue closed")

    @property
    def is_closed(self) -> bool:
        """Check if queue is closed."""
        return self._closed

    @property
    def subscriber_count(self) -> int:
        """Get number of active subscribers."""
        return self._subscribers

    @property
    def created_at(self) -> datetime:
        """Get queue creation timestamp."""
        return self._created_at

    @property
    def last_activity(self) -> datetime:
        """Get last activity timestamp."""
        return self._last_activity

    def is_stale(self, timeout_hours: int = STALE_QUEUE_TIMEOUT_HOURS) -> bool:
        """
        Check if queue is stale (no subscribers and no activity for timeout period).

        Args:
            timeout_hours: Hours of inactivity before queue is considered stale

        Returns:
            True if queue is stale and can be cleaned up
        """
        if self._subscribers > 0:
            return False

        stale_threshold = datetime.now(UTC) - timedelta(hours=timeout_hours)
        return self._last_activity < stale_threshold


# =============================================================================
# GLOBAL REGISTRY
# =============================================================================
# Manages multiple concurrent workflows by thread_id

_progress_queues: dict[str, ProgressQueue] = {}


def get_progress_queue(thread_id: str) -> ProgressQueue:
    """
    Get or create a progress queue for a specific workflow thread.

    Also performs opportunistic cleanup of stale queues to prevent memory leaks.

    Args:
        thread_id: Unique identifier for the workflow
                   (e.g., "periodic_newsletter_langtalks_2025-10-01")

    Returns:
        ProgressQueue instance for this thread
    """
    if thread_id not in _progress_queues:
        # Opportunistic cleanup when creating new queues
        cleanup_stale_queues()

        _progress_queues[thread_id] = ProgressQueue()
        logger.info(f"Created new progress queue for thread: {thread_id}")

    return _progress_queues[thread_id]


def remove_progress_queue(thread_id: str) -> None:
    """
    Remove and close a progress queue for a completed workflow.

    Args:
        thread_id: Thread ID to cleanup
    """
    if thread_id in _progress_queues:
        queue = _progress_queues[thread_id]
        queue.close()
        del _progress_queues[thread_id]
        logger.info(f"Removed progress queue for thread: {thread_id}")


def cleanup_stale_queues() -> int:
    """
    Clean up stale progress queues (no subscribers and no activity for 2 hours).

    This function is called opportunistically when new queues are created to
    prevent memory leaks from abandoned workflows.

    Returns:
        Number of stale queues removed
    """
    stale_thread_ids = [thread_id for thread_id, queue in _progress_queues.items() if queue.is_stale()]

    for thread_id in stale_thread_ids:
        queue = _progress_queues[thread_id]
        queue.close()
        del _progress_queues[thread_id]
        logger.info(f"Cleaned up stale progress queue: {thread_id}")

    if stale_thread_ids:
        logger.info(f"Cleaned up {len(stale_thread_ids)} stale progress queues")

    return len(stale_thread_ids)
