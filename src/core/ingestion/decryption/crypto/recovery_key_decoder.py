"""
Decode and validate Matrix/Beeper recovery codes.

Matrix recovery key format:
- Prefix: [0x8B, 0x01] (2 bytes)
- Key: 32 bytes (Curve25519 private key)
- Parity: 1 byte (XOR of all preceding bytes)
- Encoding: Base58 with Bitcoin alphabet
- Display: Spaces added every 4 characters (ignored when parsing)

Reference:
- https://spec.matrix.org/unstable/appendices/#cryptographic-key-representation
- https://matrix-org.github.io/matrix-rust-sdk/src/matrix_sdk_crypto/backups/keys/decryption.rs.html
"""

import logging

from core.ingestion.decryption.exceptions import InvalidRecoveryCodeError

logger = logging.getLogger(__name__)

# Bitcoin alphabet for Base58
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Matrix recovery key prefix
PREFIX = bytes([0x8B, 0x01])
PREFIX_LENGTH = 2
KEY_LENGTH = 32
PARITY_LENGTH = 1
TOTAL_LENGTH = PREFIX_LENGTH + KEY_LENGTH + PARITY_LENGTH  # 35 bytes


class RecoveryKeyDecoder:
    """
    Decode Matrix/Beeper recovery codes to Curve25519 private keys.

    Usage:
        decoder = RecoveryKeyDecoder()
        private_key = decoder.decode("EsTs Uqkz x5wN YQP6 VxLM...")
    """

    def decode(self, recovery_code: str) -> bytes:
        """
        Decode a recovery code to a 32-byte Curve25519 private key.

        Args:
            recovery_code: Base58-encoded recovery code (spaces allowed)

        Returns:
            32-byte private key

        Raises:
            InvalidRecoveryCodeError: If the code is malformed
        """
        # Remove all whitespace
        clean_code = "".join(recovery_code.split())

        if not clean_code:
            raise InvalidRecoveryCodeError("Recovery code is empty")

        # Base58 decode
        try:
            data = self._base58_decode(clean_code)
        except Exception as e:
            raise InvalidRecoveryCodeError(f"Invalid Base58 encoding: {e}")

        # Check length
        if len(data) < TOTAL_LENGTH:
            raise InvalidRecoveryCodeError(f"Recovery code too short: got {len(data)} bytes, expected {TOTAL_LENGTH}")

        if len(data) > TOTAL_LENGTH:
            raise InvalidRecoveryCodeError(f"Recovery code too long: got {len(data)} bytes, expected {TOTAL_LENGTH}")

        # Verify prefix
        if data[:PREFIX_LENGTH] != PREFIX:
            raise InvalidRecoveryCodeError(f"Invalid prefix: expected {PREFIX.hex()}, got {data[:PREFIX_LENGTH].hex()}")

        # Extract key
        key = data[PREFIX_LENGTH : PREFIX_LENGTH + KEY_LENGTH]

        # Extract and verify parity
        parity_byte = data[PREFIX_LENGTH + KEY_LENGTH]
        calculated_parity = self._calculate_parity(data[: PREFIX_LENGTH + KEY_LENGTH])

        if parity_byte != calculated_parity:
            raise InvalidRecoveryCodeError(f"Parity check failed: expected {calculated_parity:02x}, got {parity_byte:02x}")

        logger.debug(f"Successfully decoded recovery key ({KEY_LENGTH} bytes)")
        return key

    def validate(self, recovery_code: str) -> bool:
        """
        Check if a recovery code is valid without raising exceptions.

        Args:
            recovery_code: Base58-encoded recovery code

        Returns:
            True if valid, False otherwise
        """
        try:
            self.decode(recovery_code)
            return True
        except InvalidRecoveryCodeError:
            return False

    def _base58_decode(self, data: str) -> bytes:
        """
        Decode Base58-encoded string using Bitcoin alphabet.

        Args:
            data: Base58-encoded string

        Returns:
            Decoded bytes
        """
        # Convert to number
        num = 0
        for char in data:
            if char not in ALPHABET:
                raise ValueError(f"Invalid Base58 character: {char}")
            num = num * 58 + ALPHABET.index(char)

        # Convert to bytes
        result = []
        while num > 0:
            result.append(num % 256)
            num //= 256

        # Handle leading zeros (represented as '1' in Base58)
        leading_ones = len(data) - len(data.lstrip("1"))
        result.extend([0] * leading_ones)

        return bytes(reversed(result))

    def _calculate_parity(self, data: bytes) -> int:
        """
        Calculate XOR parity of all bytes.

        Args:
            data: Input bytes

        Returns:
            XOR of all bytes
        """
        parity = 0
        for byte in data:
            parity ^= byte
        return parity
