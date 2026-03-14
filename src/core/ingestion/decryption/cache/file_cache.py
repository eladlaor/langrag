"""JSON file-based cache implementation for decryption keys.

Extracted from matrix_decryption/key_manager.py to follow DRY principle.
"""

import json
import logging
from pathlib import Path
from typing import Any

from core.ingestion.decryption.exceptions import CacheError
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class JSONFileCacheAdapter:
    """
    JSON file-based cache for decryption keys.

    Implements caching with deduplication based on (room_id, session_id) tuples.
    """

    def __init__(self, cache_path: Path):
        """
        Initialize the cache adapter.

        Args:
            cache_path: Path to JSON cache file
        """
        self.cache_path = cache_path

    def load(self) -> list[dict[str, Any]]:
        """Load keys from the cache.

        Returns:
            List of cached key dictionaries. Returns empty list if cache doesn't exist.

        Raises:
            CacheError: If cache exists but cannot be read
        """
        if not self.cache_path.exists():
            return []

        try:
            with open(self.cache_path) as f:
                cached = json.load(f)
                logger.debug(f"Loaded {len(cached)} keys from cache at {self.cache_path}")
                return cached
        except (OSError, json.JSONDecodeError) as e:
            raise CacheError(f"Failed to load cache from {self.cache_path}: {e}")

    def save(self, keys: list[dict[str, Any]]) -> None:
        """Save keys to the cache.

        Args:
            keys: List of key dictionaries to save

        Raises:
            CacheError: If keys cannot be written to cache
        """
        # Ensure directory exists
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.cache_path, "w") as f:
                json.dump(keys, f, indent=2)
            logger.debug(f"Saved {len(keys)} keys to cache at {self.cache_path}")
        except OSError as e:
            raise CacheError(f"Failed to save cache to {self.cache_path}: {e}")

    def merge(self, new_keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge new keys with existing cached keys (deduplication).

        Deduplicates based on (room_id, session_id) tuples.
        New keys take precedence over existing keys with the same ID.

        Args:
            new_keys: New keys to merge into cache

        Returns:
            Combined list of all keys (existing + new, deduplicated)

        Raises:
            CacheError: If merge operation fails
        """
        try:
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

        except Exception as e:
            if isinstance(e, CacheError):
                raise
            raise CacheError(f"Failed to merge keys: {e}")

    def exists(self) -> bool:
        """Check if cache exists.

        Returns:
            True if cache file exists, False otherwise
        """
        return self.cache_path.exists()

    def clear(self) -> None:
        """Clear all keys from cache.

        Raises:
            CacheError: If cache cannot be cleared
        """
        try:
            if self.cache_path.exists():
                self.cache_path.unlink()
                logger.info(f"Cleared cache at {self.cache_path}")
        except OSError as e:
            raise CacheError(f"Failed to clear cache at {self.cache_path}: {e}")

    def get_location(self) -> Path | None:
        """Get the location of the cache (for logging).

        Returns:
            Path to cache file
        """
        return self.cache_path
