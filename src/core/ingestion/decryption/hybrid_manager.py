"""Hybrid decryption manager with fallback chain.

This manager orchestrates multiple decryption strategies in priority order,
providing automatic fallback and tracking statistics for observability.

Strategy Order (by priority):
1. PersistentSessionStrategy - Fastest, works for recent messages
2. ServerBackupStrategy - Requires recovery code, comprehensive coverage
3. ManualExportStrategy - Fallback for older messages, requires manual export

The manager tries each strategy in order and returns the first successful decryption.
"""

import logging
from typing import Any
from dataclasses import dataclass, field

from core.ingestion.decryption.strategies.base import DecryptionStrategyInterface
from constants import MatrixEventType
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


@dataclass
class DecryptionStatistics:
    """Statistics for decryption operations."""

    total_attempts: int = 0
    total_successes: int = 0
    total_failures: int = 0

    # Per-strategy statistics
    strategy_successes: dict[str, int] = field(default_factory=dict)
    strategy_failures: dict[str, int] = field(default_factory=dict)

    def record_success(self, strategy_name: str) -> None:
        """Record a successful decryption."""
        self.total_attempts += 1
        self.total_successes += 1
        self.strategy_successes[strategy_name] = self.strategy_successes.get(strategy_name, 0) + 1

    def record_failure(self) -> None:
        """Record a failed decryption (all strategies failed)."""
        self.total_attempts += 1
        self.total_failures += 1

    def get_success_rate(self) -> float:
        """Calculate overall success rate."""
        if self.total_attempts == 0:
            return 0.0
        return self.total_successes / self.total_attempts

    def get_summary(self) -> dict[str, Any]:
        """Get statistics summary."""
        return {
            "total_attempts": self.total_attempts,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": self.get_success_rate(),
            "strategy_successes": self.strategy_successes,
            "strategy_failures": self.strategy_failures,
        }


class HybridDecryptionManager:
    """
    Manages multiple decryption strategies with automatic fallback.

    Tries strategies in order until one succeeds. Tracks statistics
    for observability and debugging.

    Usage:
        manager = HybridDecryptionManager(strategies=[
            PersistentSessionStrategy(client),
            ServerBackupStrategy(key_manager),
            ManualExportStrategy(keys_file_path),
        ])
        await manager.initialize()

        # Decrypt a message
        result = await manager.decrypt_message(encrypted_event, room_id)

        # Get statistics
        stats = manager.get_statistics()
    """

    def __init__(self, strategies: list[DecryptionStrategyInterface]):
        """
        Initialize the hybrid decryption manager.

        Args:
            strategies: List of decryption strategies in priority order
                       (first strategy is tried first)

        Raises:
            ValueError: If strategies list is empty
        """
        if not strategies:
            raise ValueError("At least one decryption strategy is required")

        self.strategies = strategies
        self.stats = DecryptionStatistics()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all strategies.

        Initializes each strategy in order. If a strategy fails to initialize,
        it logs a warning but continues with other strategies.
        """
        if self._initialized:
            return

        logger.info(f"Initializing hybrid decryption manager with {len(self.strategies)} strategies")

        for strategy in self.strategies:
            try:
                strategy_name = strategy.get_strategy_name()
                logger.debug(f"Initializing strategy: {strategy_name}")
                await strategy.initialize()
                logger.info(f"Strategy initialized: {strategy_name}")
            except Exception as e:
                strategy_name = strategy.get_strategy_name()
                logger.warning(f"Failed to initialize strategy {strategy_name}: {e}. " f"Will continue with other strategies.")

        self._initialized = True
        logger.info("Hybrid decryption manager initialized")

    async def decrypt_message(self, encrypted_event: dict[str, Any], room_id: str) -> dict[str, Any] | None:
        """
        Attempt to decrypt a message using available strategies.

        Tries each strategy in order until one succeeds. Returns None if
        all strategies fail (message remains encrypted).

        Args:
            encrypted_event: Dictionary representation of encrypted Matrix event
            room_id: Matrix room ID where the message was sent

        Returns:
            Decrypted message dictionary if successful, None if all strategies failed
        """
        if not self._initialized:
            raise RuntimeError("HybridDecryptionManager not initialized. Call initialize() first.")

        # Skip non-encrypted messages
        if encrypted_event.get("type") != MatrixEventType.ROOM_ENCRYPTED:
            return None

        event_id = encrypted_event.get(DecryptionResultKeys.EVENT_ID, "unknown")

        # Try each strategy in order
        for strategy in self.strategies:
            try:
                strategy_name = strategy.get_strategy_name()
                logger.debug(f"Trying {strategy_name} for event {event_id}")

                result = await strategy.decrypt_message(encrypted_event, room_id)

                if result:
                    # Success - record and return
                    self.stats.record_success(strategy_name)
                    logger.debug(f"Decrypted {event_id} with {strategy_name} " f"(success rate: {self.stats.get_success_rate():.1%})")
                    return result
                else:
                    # Strategy couldn't decrypt - try next one
                    logger.debug(f"Strategy {strategy_name} could not decrypt {event_id}")

            except Exception as e:
                strategy_name = strategy.get_strategy_name()
                logger.debug(f"Strategy {strategy_name} failed for {event_id}: {e}")
                # Continue to next strategy

        # All strategies failed
        self.stats.record_failure()
        logger.debug(f"Failed to decrypt {event_id} with any strategy " f"(success rate: {self.stats.get_success_rate():.1%})")
        return None

    async def cleanup(self) -> None:
        """Cleanup all strategies and resources."""
        logger.info("Cleaning up hybrid decryption manager")

        for strategy in self.strategies:
            try:
                strategy_name = strategy.get_strategy_name()
                logger.debug(f"Cleaning up strategy: {strategy_name}")
                await strategy.cleanup()
            except Exception as e:
                strategy_name = strategy.get_strategy_name()
                logger.warning(f"Error cleaning up strategy {strategy_name}: {e}")

        self._initialized = False
        logger.info("Hybrid decryption manager cleaned up")

    def get_statistics(self) -> dict[str, Any]:
        """
        Get decryption statistics.

        Returns:
            Dictionary with statistics including:
            - total_attempts: Total decryption attempts
            - total_successes: Total successful decryptions
            - total_failures: Total failed decryptions
            - success_rate: Overall success rate (0.0-1.0)
            - strategy_successes: Success count per strategy
            - strategy_failures: Failure count per strategy
        """
        return self.stats.get_summary()

    def get_strategy_names(self) -> list[str]:
        """
        Get names of all configured strategies in priority order.

        Returns:
            List of strategy names
        """
        return [strategy.get_strategy_name() for strategy in self.strategies]
