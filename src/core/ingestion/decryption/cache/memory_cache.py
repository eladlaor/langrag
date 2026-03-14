"""In-memory cache implementation for testing.

Provides a simple in-memory cache that implements the same interface as JSONFileCacheAdapter.
"""

import logging
from pathlib import Path
from typing import Any

from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class InMemoryCacheAdapter:
    """
    In-memory cache for decryption keys (useful for testing).

    Implements the same interface as JSONFileCacheAdapter but stores keys in memory.
    """

    def __init__(self):
        """Initialize the in-memory cache."""
        self._keys: list[dict[str, Any]] = []

    def load(self) -> list[dict[str, Any]]:
        """Load keys from memory.

        Returns:
            List of cached key dictionaries
        """
        return self._keys.copy()

    def save(self, keys: list[dict[str, Any]]) -> None:
        """Save keys to memory.

        Args:
            keys: List of key dictionaries to save
        """
        self._keys = keys.copy()
        logger.debug(f"Saved {len(keys)} keys to in-memory cache")

    def merge(self, new_keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge new keys with existing cached keys (deduplication).

        Deduplicates based on (room_id, session_id) tuples.
        New keys take precedence over existing keys with the same ID.

        Args:
            new_keys: New keys to merge into cache

        Returns:
            Combined list of all keys (existing + new, deduplicated)
        """
        existing_keys = self.load()
        merged = {}

        # Add existing keys first
        for key in existing_keys:
            uid = (key.get(DecryptionResultKeys.ROOM_ID), key.get(DecryptionResultKeys.SESSION_ID))
            merged[uid] = key

        # Add/update with new keys
        added_count = 0
        updated_count = 0

        for key in new_keys:
            uid = (key.get(DecryptionResultKeys.ROOM_ID), key.get(DecryptionResultKeys.SESSION_ID))
            if uid in merged:
                updated_count += 1
            else:
                added_count += 1
            merged[uid] = key

        result = list(merged.values())

        logger.info(f"Merged keys: {len(existing_keys)} existing, " f"{added_count} added, {updated_count} updated, " f"{len(result)} total")

        # Save merged result
        self.save(result)

        return result

    def exists(self) -> bool:
        """Check if cache has any keys.

        Returns:
            True if cache contains keys, False otherwise
        """
        return len(self._keys) > 0

    def clear(self) -> None:
        """Clear all keys from cache."""
        self._keys = []
        logger.info("Cleared in-memory cache")

    def get_location(self) -> Path | None:
        """Get the location of the cache (for logging).

        Returns:
            None (in-memory cache has no file location)
        """
        return None
