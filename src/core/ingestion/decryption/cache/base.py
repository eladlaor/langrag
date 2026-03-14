"""Base interface for key caching.

This module defines the protocol for key cache implementations.
"""

from typing import Protocol, Any
from pathlib import Path


class CacheInterface(Protocol):
    """Protocol for key cache implementations.

    Provides persistent storage for decryption keys with deduplication and merging.
    """

    def load(self) -> list[dict[str, Any]]:
        """Load keys from the cache.

        Returns:
            List of cached key dictionaries. Returns empty list if cache doesn't exist.

        Raises:
            CacheError: If cache exists but cannot be read
        """
        ...

    def save(self, keys: list[dict[str, Any]]) -> None:
        """Save keys to the cache.

        Args:
            keys: List of key dictionaries to save

        Raises:
            CacheError: If keys cannot be written to cache
        """
        ...

    def merge(self, new_keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge new keys with existing cached keys (deduplication).

        Args:
            new_keys: New keys to merge into cache

        Returns:
            Combined list of all keys (existing + new, deduplicated)

        Raises:
            CacheError: If merge operation fails
        """
        ...

    def exists(self) -> bool:
        """Check if cache exists.

        Returns:
            True if cache file/storage exists, False otherwise
        """
        ...

    def clear(self) -> None:
        """Clear all keys from cache.

        Raises:
            CacheError: If cache cannot be cleared
        """
        ...

    def get_location(self) -> Path | None:
        """Get the location of the cache (for logging).

        Returns:
            Path to cache file, or None if cache is in-memory
        """
        ...
