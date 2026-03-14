"""
Decrypt Megolm sessions from Matrix server-side backup.

Algorithm: m.megolm_backup.v1.curve25519-aes-sha2

Process:
1. ECDH: X25519 key exchange (recovery private + ephemeral public)
2. HKDF-SHA256: Derive 80 bytes with salt=32 zero bytes, info=empty
   - Bytes 0-31: AES-256 key
   - Bytes 32-63: MAC key (unused - historical bug)
   - Bytes 64-79: AES IV
3. AES-256-CBC decrypt with PKCS7 unpadding

Reference:
- https://spec.matrix.org/latest/client-server-api/#server-side-key-backups
- https://matrix-org.github.io/matrix-rust-sdk/src/matrix_sdk_crypto/backups/keys/decryption.rs.html
"""

import base64
import json
import logging
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from core.ingestion.decryption.exceptions import SessionDecryptionError

logger = logging.getLogger(__name__)


class SessionDecryptor:
    """
    Decrypt Megolm sessions from Matrix server-side backup.

    Usage:
        decryptor = SessionDecryptor(recovery_private_key)
        session_data = decryptor.decrypt(encrypted_session)
    """

    # HKDF parameters (per Matrix spec)
    HKDF_SALT = b"\x00" * 32  # 32 zero bytes
    HKDF_INFO = b""  # Empty info
    HKDF_OUTPUT_LENGTH = 80  # 32 (AES) + 32 (MAC) + 16 (IV)

    # Key derivation output positions
    AES_KEY_START = 0
    AES_KEY_END = 32
    MAC_KEY_START = 32
    MAC_KEY_END = 64
    IV_START = 64
    IV_END = 80

    def __init__(self, recovery_private_key: bytes):
        """
        Initialize the decryptor with the recovery private key.

        Args:
            recovery_private_key: 32-byte Curve25519 private key (from RecoveryKeyDecoder)
        """
        if len(recovery_private_key) != 32:
            raise ValueError(f"Private key must be 32 bytes, got {len(recovery_private_key)}")

        self._private_key = recovery_private_key

    def decrypt(self, session_data: dict[str, str]) -> dict[str, Any]:
        """
        Decrypt a backed-up Megolm session.

        Args:
            session_data: Dict with keys: ephemeral, ciphertext, mac

        Returns:
            Decrypted session data dict containing:
            - algorithm: str (e.g., "m.megolm.v1.aes-sha2")
            - sender_key: str (Curve25519 key of sender)
            - session_key: str (the actual Megolm session key)
            - forwarding_curve25519_key_chain: list

        Raises:
            SessionDecryptionError: If decryption fails
        """
        try:
            # Extract and decode fields
            ephemeral = base64.b64decode(session_data["ephemeral"])
            ciphertext = base64.b64decode(session_data["ciphertext"])
            # mac = base64.b64decode(session_data["mac"])  # Not verified (historical bug)

            # Perform ECDH to get shared secret
            shared_secret = self._ecdh(ephemeral)

            # Derive AES key and IV using HKDF
            aes_key, _, iv = self._derive_keys(shared_secret)

            # Note: MAC verification is skipped
            # The original libolm implementation had a bug where it passed
            # an empty buffer instead of the ciphertext to HMAC.
            # For compatibility, we don't verify the MAC.

            # AES-256-CBC decrypt
            plaintext = self._decrypt_aes_cbc(ciphertext, aes_key, iv)

            # Parse JSON
            return json.loads(plaintext.decode("utf-8"))

        except KeyError as e:
            raise SessionDecryptionError(f"Missing required field: {e}")
        except json.JSONDecodeError as e:
            raise SessionDecryptionError(f"Invalid JSON in decrypted data: {e}")
        except Exception as e:
            raise SessionDecryptionError(f"Decryption failed: {e}")

    def _ecdh(self, ephemeral_public: bytes) -> bytes:
        """
        Perform X25519 Elliptic Curve Diffie-Hellman key exchange.

        Args:
            ephemeral_public: 32-byte public key from the encrypted session

        Returns:
            32-byte shared secret
        """
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
            X25519PublicKey,
        )

        private = X25519PrivateKey.from_private_bytes(self._private_key)
        public = X25519PublicKey.from_public_bytes(ephemeral_public)
        return private.exchange(public)

    def _derive_keys(self, shared_secret: bytes) -> tuple:
        """
        Derive AES key, MAC key, and IV from shared secret using HKDF-SHA256.

        Args:
            shared_secret: 32-byte ECDH shared secret

        Returns:
            Tuple of (aes_key: bytes, mac_key: bytes, iv: bytes)
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=self.HKDF_OUTPUT_LENGTH,
            salt=self.HKDF_SALT,
            info=self.HKDF_INFO,
            backend=default_backend(),
        )
        derived = hkdf.derive(shared_secret)

        aes_key = derived[self.AES_KEY_START : self.AES_KEY_END]
        mac_key = derived[self.MAC_KEY_START : self.MAC_KEY_END]
        iv = derived[self.IV_START : self.IV_END]

        return aes_key, mac_key, iv

    def _decrypt_aes_cbc(self, ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        """
        Decrypt using AES-256-CBC with PKCS7 unpadding.

        Args:
            ciphertext: Encrypted data
            key: 32-byte AES key
            iv: 16-byte initialization vector

        Returns:
            Decrypted and unpadded plaintext
        """
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        # PKCS7 unpadding
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()

        return plaintext
