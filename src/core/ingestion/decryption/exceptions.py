"""Decryption-related exception classes.

This module centralizes all exception types used across the decryption subsystem.
"""


class DecryptionError(Exception):
    """Base exception for all decryption-related errors."""

    pass


class InvalidRecoveryCodeError(DecryptionError):
    """Raised when recovery code format is invalid or checksum fails."""

    pass


class SessionDecryptionError(DecryptionError):
    """Raised when Megolm session decryption fails."""

    pass


class BackupNotFoundError(DecryptionError):
    """Raised when no server-side backup is configured."""

    pass


class PublicKeyMismatchError(DecryptionError):
    """Raised when the backup public key doesn't match the recovery key."""

    pass


class CacheError(DecryptionError):
    """Raised when cache operations fail."""

    pass


class KeyManagementError(DecryptionError):
    """Raised when key management operations fail."""

    pass
