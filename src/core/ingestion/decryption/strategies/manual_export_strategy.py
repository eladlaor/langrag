"""Manual export decryption strategy.

This strategy uses manually exported keys (from Element Web UI or similar)
to decrypt messages.
"""

import logging
import json
from typing import Any
from olm import InboundGroupSession

from core.ingestion.decryption.key_management import ManualKeyLoader
from core.ingestion.decryption.crypto import MegolmExportDecryptor
from core.ingestion.decryption.exceptions import DecryptionError, KeyManagementError
from constants import MatrixEventType, MatrixEncryptionAlgorithm, MATRIX_KEY_RELATES_TO, DecryptionMethod
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class ManualExportStrategy:
    """
    Decryption strategy using manually exported keys.

    Loads keys from a JSON file (either already decrypted or encrypted with passphrase)
    and uses them to decrypt messages.
    """

    def __init__(self, keys_file_path: str, passphrase: str | None = None):
        """
        Initialize the manual export strategy.

        Args:
            keys_file_path: Path to the keys file (decrypted JSON or encrypted export)
            passphrase: Optional passphrase if keys file is encrypted (element-keys.txt format)
        """
        self.keys_file_path = keys_file_path
        self.passphrase = passphrase
        self._keys: list[dict[str, Any]] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the strategy by loading keys from file.

        Loads and optionally decrypts keys from the manual export file.
        """
        if self._initialized:
            return

        try:
            if self.passphrase:
                # Encrypted export file - decrypt it
                logger.info(f"Loading encrypted manual export from {self.keys_file_path}")
                decryptor = MegolmExportDecryptor()
                self._keys = decryptor.load_and_decrypt_export_file(self.keys_file_path, self.passphrase)
            else:
                # Already decrypted JSON file
                logger.info(f"Loading decrypted manual export from {self.keys_file_path}")
                loader = ManualKeyLoader()
                self._keys = loader.load_keys(self.keys_file_path)

            self._initialized = True
            logger.info(f"Manual export strategy initialized with {len(self._keys)} keys")

        except (DecryptionError, KeyManagementError) as e:
            logger.warning(f"Failed to initialize manual export strategy: {e}")
            # Don't raise - allow fallback to other strategies
            self._initialized = True  # Mark as initialized to avoid retry

    async def decrypt_message(self, encrypted_event: dict[str, Any], room_id: str) -> dict[str, Any] | None:
        """Attempt to decrypt a message using manual export keys.

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

            # Find matching session key from manual export
            session_key = None
            for entry in self._keys:
                if entry.get("sender_key") == sender_key and entry.get(DecryptionResultKeys.ROOM_ID) == room_id and entry.get(DecryptionResultKeys.SESSION_ID) == session_id:
                    session_key = entry.get("session_key")
                    break

            if not session_key:
                # No matching key found - try other strategies
                return None

            # Decrypt using manual export key
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
            result[DecryptionResultKeys.DECRYPTION_METHOD] = DecryptionMethod.MANUAL_EXPORT

            logger.debug(f"Decrypted with manual export: {encrypted_event.get(DecryptionResultKeys.EVENT_ID)}")
            return result

        except Exception as e:
            logger.debug(f"Manual export decryption failed: {e}")
            return None

    async def cleanup(self) -> None:
        """Cleanup resources held by this strategy."""
        self._keys = []
        self._initialized = False
        logger.debug("Manual export strategy cleaned up")

    def get_strategy_name(self) -> str:
        """Return human-readable name of this strategy for logging."""
        return DecryptionMethod.MANUAL_EXPORT
