"""Megolm session export decryption.

This module handles decryption of Megolm session export files (element-keys.txt format)
exported from Element/Matrix clients.

Extracted from beeper.py to follow DRY principle and separation of concerns.
"""

import base64
import hmac
import hashlib
import struct
import logging
from typing import Any
import json

from Crypto.Util import Counter
from Crypto.Cipher import AES

from core.ingestion.decryption.exceptions import DecryptionError

logger = logging.getLogger(__name__)


class MegolmExportDecryptor:
    """
    Decrypt Megolm session export files.

    Implements the Matrix key export format specification for encrypted
    key exports from Element/Matrix clients.
    """

    # Export format constants
    HEADER = b"-----BEGIN MEGOLM SESSION DATA-----"
    FOOTER = b"-----END MEGOLM SESSION DATA-----"
    MAC_SIZE = 32

    def decrypt_export(self, passphrase: str, session_data: bytes) -> bytes:
        """
        Decrypt a megolm session export file.

        Args:
            passphrase: The password used during export
            session_data: Raw bytes of the exported file

        Returns:
            Decrypted JSON bytes

        Raises:
            DecryptionError: If decryption fails (wrong password or corrupted data)
        """
        try:
            # Parse format: version(1) + salt(16) + iv(16) + rounds(4)
            CryptoParams = struct.Struct(">c16s16sL")

            # Strip and validate
            session_data = session_data.strip()
            if not session_data.startswith(self.HEADER):
                raise ValueError("Invalid export file: missing header")
            if not session_data.endswith(self.FOOTER):
                raise ValueError("Invalid export file: missing footer")

            # Extract and decode body
            body = base64.b64decode(session_data[len(self.HEADER) : -len(self.FOOTER)])

            if len(body) < CryptoParams.size + self.MAC_SIZE:
                raise ValueError("Invalid export file: data too small")

            # Unpack parameters
            params = body[: CryptoParams.size]
            version, salt, iv_bytes, rounds = CryptoParams.unpack(params)
            iv = int.from_bytes(iv_bytes, byteorder="big")

            # Derive keys using PBKDF2
            if not isinstance(passphrase, bytes):
                passphrase = passphrase.encode("utf-8")
            keys = hashlib.pbkdf2_hmac("sha512", passphrase, salt, rounds, dklen=64)
            K, Kp = keys[:32], keys[32:]

            # Verify MAC
            mac = body[-self.MAC_SIZE :]
            our_mac = hmac.digest(Kp, body[: -self.MAC_SIZE], "sha256")
            if not hmac.compare_digest(mac, our_mac):
                raise ValueError("Decryption failed: wrong password or corrupted data")

            # Decrypt
            ctr = Counter.new(128, initial_value=iv)
            cipher = AES.new(K, AES.MODE_CTR, counter=ctr)
            ciphertext = body[CryptoParams.size : -self.MAC_SIZE :]

            return cipher.decrypt(ciphertext)

        except ValueError as e:
            raise DecryptionError(f"Failed to decrypt Megolm export: {e}")
        except Exception as e:
            raise DecryptionError(f"Unexpected error decrypting Megolm export: {e}")

    def load_and_decrypt_export_file(self, export_file_path: str, passphrase: str) -> list[dict[str, Any]]:
        """
        Load and decrypt a Megolm export file.

        Args:
            export_file_path: Path to the export file (element-keys.txt)
            passphrase: The password used during export

        Returns:
            List of decrypted session key dictionaries

        Raises:
            DecryptionError: If file cannot be read or decrypted
        """
        try:
            with open(export_file_path, "rb") as f:
                encrypted_data = f.read()

            decrypted_json = self.decrypt_export(passphrase, encrypted_data)
            keys = json.loads(decrypted_json.decode("utf-8"))

            logger.info(f"Successfully decrypted {len(keys)} keys from {export_file_path}")
            return keys

        except FileNotFoundError:
            raise DecryptionError(f"Export file not found: {export_file_path}")
        except json.JSONDecodeError as e:
            raise DecryptionError(f"Invalid JSON in decrypted export: {e}")
        except Exception as e:
            if isinstance(e, DecryptionError):
                raise
            raise DecryptionError(f"Failed to load export file: {e}")
