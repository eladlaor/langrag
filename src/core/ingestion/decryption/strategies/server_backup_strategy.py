"""Server backup decryption strategy.

This strategy uses Matrix server-side key backups to decrypt messages.
Requires a recovery code to be configured.
"""

import logging
import json
from typing import Any
from olm import InboundGroupSession

from core.ingestion.decryption.key_management import MatrixKeyBackupManager
from constants import MatrixEventType, MatrixEncryptionAlgorithm, MATRIX_KEY_RELATES_TO, DecryptionMethod
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class ServerBackupStrategy:
    """
    Decryption strategy using Matrix server-side key backups.

    Downloads and caches keys from the Matrix homeserver using the
    recovery code, then uses those keys to decrypt messages.
    """

    def __init__(self, key_manager: MatrixKeyBackupManager):
        """
        Initialize the server backup strategy.

        Args:
            key_manager: Configured MatrixKeyBackupManager instance
        """
        self.key_manager = key_manager
        self._keys: list[dict[str, Any]] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the strategy by syncing keys from server.

        Downloads all backed up keys from the server and caches them locally.
        """
        if self._initialized:
            return

        try:
            logger.info("Syncing keys from Matrix server backup...")
            self._keys = await self.key_manager.sync_keys()
            self._initialized = True
            logger.info(f"Server backup strategy initialized with {len(self._keys)} keys")
        except Exception as e:
            logger.warning(f"Failed to initialize server backup strategy: {e}")
            # Don't raise - allow fallback to other strategies
            self._initialized = True  # Mark as initialized to avoid retry

    async def decrypt_message(self, encrypted_event: dict[str, Any], room_id: str) -> dict[str, Any] | None:
        """Attempt to decrypt a message using server backup keys.

        Args:
            encrypted_event: Dictionary representation of encrypted Matrix event
            room_id: Matrix room ID where the message was sent

        Returns:
            Decrypted message dictionary if successful, None if cannot decrypt
        """
        # Skip non-encrypted messages
        if encrypted_event.get("type") != MatrixEventType.ROOM_ENCRYPTED:
            return None

        # Extract encryption details
        content = encrypted_event.get("content", {})
        algorithm = content.get("algorithm")

        # Only handle Megolm encrypted messages
        if algorithm != MatrixEncryptionAlgorithm.MEGOLM_V1_AES_SHA2:
            return None

        try:
            ciphertext = content.get("ciphertext")
            sender_key = content.get("sender_key")
            session_id = content.get("session_id")

            # Verify we have all required encryption information
            if not all([ciphertext, room_id, sender_key, session_id]):
                return None

            # Find matching session key from server backup
            session_key = None
            for entry in self._keys:
                if entry.get("sender_key") == sender_key and entry.get(DecryptionResultKeys.ROOM_ID) == room_id and entry.get(DecryptionResultKeys.SESSION_ID) == session_id:
                    session_key = entry.get("session_key")
                    break

            if not session_key:
                # No matching key found - try other strategies
                return None

            # Decrypt using server backup key
            session = InboundGroupSession.import_session(session_key)
            decrypted_payload, _ = session.decrypt(ciphertext)

            # Parse the decrypted JSON payload
            decrypted_content = json.loads(decrypted_payload)

            # Build result
            result = encrypted_event.copy()
            result[DecryptionResultKeys.CONTENT] = decrypted_content.get(DecryptionResultKeys.CONTENT, {})
            result["type"] = decrypted_content.get("type", MatrixEventType.ROOM_MESSAGE)

            # Preserve m.relates_to from encrypted wrapper (critical for reply threading)
            if MATRIX_KEY_RELATES_TO in content:
                result[DecryptionResultKeys.CONTENT][MATRIX_KEY_RELATES_TO] = content[MATRIX_KEY_RELATES_TO]

            # Flag that this message was decrypted
            result[DecryptionResultKeys.DECRYPTED] = True
            result[DecryptionResultKeys.DECRYPTION_METHOD] = DecryptionMethod.SERVER_BACKUP

            logger.debug(f"Decrypted with server backup: {encrypted_event.get(DecryptionResultKeys.EVENT_ID)}")
            return result

        except Exception as e:
            logger.debug(f"Server backup decryption failed: {e}")
            return None

    async def cleanup(self) -> None:
        """Cleanup resources held by this strategy."""
        self._keys = []
        self._initialized = False
        logger.debug("Server backup strategy cleaned up")

    def get_strategy_name(self) -> str:
        """Return human-readable name of this strategy for logging."""
        return DecryptionMethod.SERVER_BACKUP
