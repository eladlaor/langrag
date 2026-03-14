"""
Persistence policy configuration for MongoDB operations.

Provides standardized error handling for database persistence operations
with configurable fail-fast vs fail-soft behavior.
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class PersistencePolicy(Enum):
    """Policy for handling persistence failures."""

    FAIL_HARD = "fail_hard"  # Raise exception on failure
    FAIL_SOFT = "fail_soft"  # Log warning, continue execution


def handle_persistence_error(error: Exception, operation: str, policy: PersistencePolicy = PersistencePolicy.FAIL_SOFT, context: dict | None = None) -> None:
    """
    Handle persistence errors according to policy.

    Args:
        error: The exception that occurred
        operation: Description of the operation that failed
        policy: How to handle the failure (FAIL_HARD or FAIL_SOFT)
        context: Additional context for logging (e.g., IDs, counts)

    Raises:
        RuntimeError: If policy is FAIL_HARD

    Example:
        try:
            await tracker.store_messages(...)
        except Exception as e:
            handle_persistence_error(
                error=e,
                operation="store_messages",
                policy=PersistencePolicy.FAIL_SOFT,
                context={"chat_name": chat_name, "message_count": 100}
            )
    """
    context_str = f", context={context}" if context else ""

    if policy == PersistencePolicy.FAIL_HARD:
        logger.error(f"Persistence failed [{operation}]: {error}{context_str}")
        raise RuntimeError(f"Failed to persist {operation}: {error}") from error
    else:
        logger.warning(f"Persistence failed (non-critical) [{operation}]: {error}{context_str}")
