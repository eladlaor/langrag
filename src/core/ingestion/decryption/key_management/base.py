"""Base interface for key management.

This module defines the protocol for key manager implementations.
"""

from typing import Protocol, Any


class KeyManagerInterface(Protocol):
    """Protocol for key manager implementations.

    Key managers are responsible for acquiring, storing, and providing
    decryption keys from various sources (server backup, manual export, etc.).
    """

    async def sync_keys(self) -> list[dict[str, Any]]:
        """Synchronize and return decryption keys.

        This method should:
        1. Fetch keys from the source (server API, file, etc.)
        2. Decrypt keys if necessary
        3. Cache keys for future use
        4. Return the complete list of available keys

        Returns:
            List of decryption key dictionaries, each containing:
            - room_id: Matrix room ID
            - session_id: Megolm session ID
            - sender_key: Curve25519 sender key
            - session_key: Decrypted Megolm session key

        Raises:
            KeyManagementError: If key synchronization fails
        """
        ...

    def get_cached_keys(self) -> list[dict[str, Any]]:
        """Get keys from local cache without re-syncing.

        Returns:
            List of cached key dictionaries, or empty list if no cache exists

        Raises:
            KeyManagementError: If cache read fails
        """
        ...
