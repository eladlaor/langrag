"""Base interface for decryption strategies.

This module defines the protocol that all decryption strategy implementations must follow.
"""

from typing import Protocol, Any


class DecryptionStrategyInterface(Protocol):
    """Protocol for decryption strategy implementations.

    All decryption strategies must implement this interface to be compatible
    with the HybridDecryptionManager.
    """

    async def initialize(self) -> None:
        """Initialize the strategy (load keys, setup client, etc.).

        Called once before the strategy is used for decryption.
        Must be idempotent (safe to call multiple times).

        Raises:
            DecryptionError: If initialization fails
        """
        ...

    async def decrypt_message(self, encrypted_event: dict[str, Any], room_id: str) -> dict[str, Any] | None:
        """Attempt to decrypt a single encrypted message.

        Args:
            encrypted_event: Dictionary representation of encrypted Matrix event
            room_id: Matrix room ID where the message was sent

        Returns:
            Decrypted message dictionary if successful, None if this strategy
            cannot decrypt this message (allows fallback to next strategy)

        Raises:
            DecryptionError: If decryption attempt fails catastrophically
                           (vs returning None for normal "can't decrypt")
        """
        ...

    async def cleanup(self) -> None:
        """Cleanup resources held by this strategy.

        Called when the strategy is no longer needed.
        Must be idempotent (safe to call multiple times).
        """
        ...

    def get_strategy_name(self) -> str:
        """Return human-readable name of this strategy for logging.

        Returns:
            Strategy name (e.g., "persistent_session", "manual_export")
        """
        ...
