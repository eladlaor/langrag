"""
Persistence helpers for LangGraph nodes.

Provides decorators and utilities for standardized MongoDB persistence
in graph nodes, reducing code duplication across nodes.
"""

import logging
import re
from typing import Any
from collections.abc import Callable

from db.persistence_policy import PersistencePolicy, handle_persistence_error
from constants import NewsletterVersionType, NewsletterType, DEFAULT_LANGUAGE
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)


def generate_newsletter_id(run_id: str, chat_name: str) -> str:
    """
    Generate standardized newsletter ID from run and chat.

    Args:
        run_id: MongoDB run ID
        chat_name: Chat name to slugify

    Returns:
        Newsletter ID in format: {run_id}_nl_{chat_slug}
    """
    chat_slug = re.sub(r"[^a-z0-9]+", "_", chat_name.lower()).strip("_")
    return f"{run_id}_nl_{chat_slug}"


async def persist_to_mongodb(operation: str, persist_func: Callable, *args, run_id: str | None = None, policy: PersistencePolicy = PersistencePolicy.FAIL_SOFT, context: dict | None = None, **kwargs) -> Any | None:
    """
    Execute MongoDB persistence with standardized error handling.

    Args:
        operation: Name of operation for logging
        persist_func: Async function to call
        *args: Positional args for persist_func
        run_id: MongoDB run ID (skip if None)
        policy: Persistence policy (FAIL_HARD or FAIL_SOFT)
        context: Additional context for error logging
        **kwargs: Keyword args for persist_func

    Returns:
        Result of persist_func, or None on soft failure
    """
    if not run_id:
        logger.debug(f"Skipping {operation}: no run_id provided")
        return None

    try:
        result = await persist_func(*args, **kwargs)
        logger.info(f"MongoDB {operation} succeeded")
        return result
    except Exception as e:
        handle_persistence_error(error=e, operation=operation, policy=policy, context=context)
        return None


class NodePersistence:
    """
    Helper class for node-level MongoDB persistence.

    Encapsulates common persistence patterns used across LangGraph nodes
    to reduce code duplication and ensure consistent error handling.

    Usage:
        persistence = NodePersistence(state)

        # Store messages
        await persistence.store_messages(messages)

        # Store discussions
        await persistence.store_discussions(discussions)

        # Store newsletter version
        await persistence.store_newsletter(
            json_path=json_path,
            md_path=md_path,
            version_type=NewsletterVersionType.ENRICHED
        )
    """

    def __init__(self, state: dict[str, Any]):
        """
        Initialize persistence helper from graph state.

        Args:
            state: LangGraph state dictionary containing run metadata
        """
        self.run_id = state.get("mongodb_run_id")
        self.chat_name = state.get("chat_name", "unknown")
        self.data_source_name = state.get("data_source_name", "")
        self.start_date = state.get("start_date", "")
        self.end_date = state.get("end_date", "")
        self.summary_format = state.get("summary_format", "")
        self.desired_language = state.get("desired_language_for_summary", DEFAULT_LANGUAGE)
        self._tracker = None

    @property
    def newsletter_id(self) -> str | None:
        """Generate newsletter ID if run_id exists."""
        if not self.run_id:
            return None
        return generate_newsletter_id(self.run_id, self.chat_name)

    @property
    def is_enabled(self) -> bool:
        """Check if MongoDB persistence is enabled (run_id exists)."""
        return self.run_id is not None

    def get_tracker(self):
        """Lazy load run tracker."""
        if self._tracker is None:
            from db.run_tracker import get_tracker

            self._tracker = get_tracker()
        return self._tracker

    async def store_messages(self, messages: list, policy: PersistencePolicy = PersistencePolicy.FAIL_SOFT) -> int | None:
        """
        Store messages to MongoDB.

        Args:
            messages: List of message dictionaries
            policy: Persistence policy (default: FAIL_SOFT)

        Returns:
            Number of messages stored, or None on failure
        """
        if not self.is_enabled:
            return None

        return await persist_to_mongodb(operation=f"store_messages({self.chat_name})", persist_func=self.get_tracker().store_messages, run_id=self.run_id, policy=policy, context={"chat_name": self.chat_name, "message_count": len(messages)}, chat_name=self.chat_name, data_source_name=self.data_source_name, messages=messages)

    async def store_discussions(self, discussions: list, policy: PersistencePolicy = PersistencePolicy.FAIL_SOFT) -> int | None:
        """
        Store discussions to MongoDB.

        Args:
            discussions: List of discussion dictionaries
            policy: Persistence policy (default: FAIL_SOFT)

        Returns:
            Number of discussions stored, or None on failure
        """
        if not self.is_enabled:
            return None

        return await persist_to_mongodb(operation=f"store_discussions({self.chat_name})", persist_func=self.get_tracker().store_discussions, run_id=self.run_id, policy=policy, context={"chat_name": self.chat_name, "discussion_count": len(discussions)}, chat_name=self.chat_name, discussions=discussions)

    async def store_newsletter(self, json_path: str, md_path: str, version_type: NewsletterVersionType = NewsletterVersionType.ORIGINAL, newsletter_type: NewsletterType = NewsletterType.PER_CHAT, stats: dict | None = None, policy: PersistencePolicy = PersistencePolicy.FAIL_SOFT) -> str | None:
        """
        Store newsletter to MongoDB.

        Args:
            json_path: Path to newsletter JSON file
            md_path: Path to newsletter markdown file
            version_type: Version type (original, enriched, translated)
            newsletter_type: Newsletter type (per_chat, consolidated)
            stats: Optional statistics dict
            policy: Persistence policy (default: FAIL_SOFT for enriched/translated,
                   but consider FAIL_HARD for original generation)

        Returns:
            Newsletter ID on success, or None on failure
        """
        if not self.is_enabled:
            return None

        return await persist_to_mongodb(
            operation=f"store_newsletter({self.newsletter_id}, {version_type})",
            persist_func=self.get_tracker().store_newsletter,
            run_id=self.run_id,
            policy=policy,
            context={DbFieldKeys.NEWSLETTER_ID: self.newsletter_id, DbFieldKeys.VERSION_TYPE: str(version_type), DbFieldKeys.CHAT_NAME: self.chat_name},
            newsletter_id=self.newsletter_id,
            newsletter_type=str(newsletter_type),
            data_source_name=self.data_source_name,
            chat_name=self.chat_name,
            start_date=self.start_date,
            end_date=self.end_date,
            summary_format=self.summary_format,
            desired_language=self.desired_language,
            json_path=json_path,
            md_path=md_path,
            stats=stats,
            version_type=str(version_type),
        )
