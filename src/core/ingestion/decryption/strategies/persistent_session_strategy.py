"""Persistent session decryption strategy.

This strategy uses the matrix-nio AsyncClient's persistent olm machine
to decrypt messages. Works for recent messages that were synced through
the client's session.
"""

import logging
from typing import Any
from nio import AsyncClient, MegolmEvent

from constants import (
    MatrixEventType,
    MatrixEncryptionAlgorithm,
    MATRIX_CONTENT_FORMAT_HTML,
    MATRIX_KEY_RELATES_TO,
    DecryptionMethod,
)
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class PersistentSessionStrategy:
    """
    Decryption strategy using matrix-nio persistent session keys.

    Uses the AsyncClient's olm machine which automatically syncs and stores
    encryption keys for recent messages.
    """

    def __init__(self, client: AsyncClient):
        """
        Initialize the persistent session strategy.

        Args:
            client: Initialized matrix-nio AsyncClient with encryption enabled
        """
        self.client = client
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the strategy.

        For persistent session, initialization is minimal since the client
        manages its own key syncing.
        """
        if self._initialized:
            return

        # Verify client has olm machine
        if not self.client.olm:
            logger.warning("Client has no olm machine - persistent session strategy disabled")
        else:
            logger.info("Persistent session strategy initialized")

        self._initialized = True

    async def decrypt_message(self, encrypted_event: dict[str, Any], room_id: str) -> dict[str, Any] | None:
        """Attempt to decrypt a message using persistent session keys.

        Args:
            encrypted_event: Dictionary representation of encrypted Matrix event
            room_id: Matrix room ID where the message was sent

        Returns:
            Decrypted message dictionary if successful, None if cannot decrypt
        """
        # Skip non-encrypted messages
        if encrypted_event.get("type") != MatrixEventType.ROOM_ENCRYPTED:
            return None

        # Check if olm machine is available
        if not self.client.olm:
            return None

        # Extract encryption details
        content = encrypted_event.get("content", {})
        algorithm = content.get("algorithm")

        # Only handle Megolm encrypted messages
        if algorithm != MatrixEncryptionAlgorithm.MEGOLM_V1_AES_SHA2:
            return None

        try:
            # Create a MegolmEvent from our dict
            megolm_event = MegolmEvent.from_dict(encrypted_event)

            # Decrypt using the client's olm machine
            decrypted_event = self.client.olm.decrypt_megolm_event(megolm_event)

            if not decrypted_event:
                # Decryption failed - try other strategies
                return None

            # Convert decrypted event to dict
            result = self._event_to_dict(decrypted_event, room_id)

            # Preserve m.relates_to from original encrypted wrapper (critical for reply threading)
            if MATRIX_KEY_RELATES_TO in content:
                result[DecryptionResultKeys.CONTENT][MATRIX_KEY_RELATES_TO] = content[MATRIX_KEY_RELATES_TO]

            # Flag that this message was decrypted
            result[DecryptionResultKeys.DECRYPTED] = True
            result[DecryptionResultKeys.DECRYPTION_METHOD] = DecryptionMethod.PERSISTENT_SESSION

            logger.debug(f"Decrypted with persistent session: {encrypted_event.get(DecryptionResultKeys.EVENT_ID)}")
            return result

        except Exception as e:
            logger.debug(f"Persistent session decryption failed: {e}")
            return None

    async def cleanup(self) -> None:
        """Cleanup resources held by this strategy.

        Note: We don't close the client here as it may be used by the extractor.
        """
        self._initialized = False
        logger.debug("Persistent session strategy cleaned up")

    def get_strategy_name(self) -> str:
        """Return human-readable name of this strategy for logging."""
        return DecryptionMethod.PERSISTENT_SESSION

    def _event_to_dict(self, event, room_id: str) -> dict[str, Any]:
        """
        Convert matrix-nio RoomMessage event to dictionary format.

        Args:
            event: RoomMessage event from matrix-nio
            room_id: The room ID where this event occurred

        Returns:
            Dictionary representation of the event
        """
        result = {DecryptionResultKeys.EVENT_ID: event.event_id, DecryptionResultKeys.SENDER: event.sender, DecryptionResultKeys.ORIGIN_SERVER_TS: event.server_timestamp, DecryptionResultKeys.TYPE: event.type if hasattr(event, "type") else MatrixEventType.ROOM_MESSAGE, DecryptionResultKeys.ROOM_ID: room_id, DecryptionResultKeys.CONTENT: {}}

        # Handle regular message events
        if hasattr(event, "body"):
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.BODY] = event.body

        if hasattr(event, "msgtype"):
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.MSGTYPE] = event.msgtype

        # Handle formatted body (HTML)
        if hasattr(event, "formatted_body"):
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.FORMATTED_BODY] = event.formatted_body
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.FORMAT] = MATRIX_CONTENT_FORMAT_HTML

        # Handle URL for media messages
        if hasattr(event, "url"):
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.URL] = event.url

        # Handle file info for media messages
        if hasattr(event, "info") and event.info:
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.INFO] = event.info

        # Capture any other content fields
        if hasattr(event, "source") and isinstance(event.source, dict):
            event_content = event.source.get(DecryptionResultKeys.CONTENT, {})
            for key, value in event_content.items():
                if key not in result[DecryptionResultKeys.CONTENT]:
                    result[DecryptionResultKeys.CONTENT][key] = value

        return result
