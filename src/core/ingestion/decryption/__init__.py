"""Matrix E2E decryption module.

This module provides decryption capabilities for Matrix encrypted messages
using a hybrid strategy pattern with automatic fallback.

Public API:
    HybridDecryptionManager - Main entry point for decryption operations
    DecryptionStrategyInterface - Protocol for custom decryption strategies

Strategies:
    PersistentSessionStrategy - Uses matrix-nio AsyncClient olm machine
    ServerBackupStrategy - Uses Matrix server-side key backups
    ManualExportStrategy - Uses manually exported keys

Crypto:
    RecoveryKeyDecoder - Decode Matrix recovery codes
    SessionDecryptor - Decrypt session data from backups
    MegolmExportDecryptor - Decrypt Megolm export files

Key Management:
    MatrixKeyBackupManager - Download and manage server-side backups
    ManualKeyLoader - Load manually exported keys

Cache:
    CacheInterface - Cache abstraction
    JSONFileCacheAdapter - File-based cache implementation
    InMemoryCache - Memory-based cache for testing

Exceptions:
    DecryptionError - Base exception
    InvalidRecoveryCodeError - Invalid recovery code format
    SessionDecryptionError - Failed to decrypt session
    BackupNotFoundError - No backup found on server
    PublicKeyMismatchError - Recovery key doesn't match backup
    CacheError - Cache operation failed
    KeyManagementError - Key management operation failed
"""

# Main API
from core.ingestion.decryption.hybrid_manager import (
    HybridDecryptionManager,
    DecryptionStatistics,
)

# Strategies
from core.ingestion.decryption.strategies.base import DecryptionStrategyInterface
from core.ingestion.decryption.strategies.persistent_session_strategy import (
    PersistentSessionStrategy,
)
from core.ingestion.decryption.strategies.server_backup_strategy import (
    ServerBackupStrategy,
)
from core.ingestion.decryption.strategies.manual_export_strategy import (
    ManualExportStrategy,
)

# Crypto utilities
from core.ingestion.decryption.crypto.recovery_key_decoder import RecoveryKeyDecoder
from core.ingestion.decryption.crypto.session_decryptor import SessionDecryptor
from core.ingestion.decryption.crypto.megolm_export_decryptor import (
    MegolmExportDecryptor,
)

# Key management
from core.ingestion.decryption.key_management.matrix_key_backup_manager import (
    MatrixKeyBackupManager,
)
from core.ingestion.decryption.key_management.manual_key_loader import ManualKeyLoader

# Cache
from core.ingestion.decryption.cache.base import CacheInterface
from core.ingestion.decryption.cache.file_cache import JSONFileCacheAdapter
from core.ingestion.decryption.cache.memory_cache import InMemoryCacheAdapter as InMemoryCache

# Exceptions
from core.ingestion.decryption.exceptions import (
    DecryptionError,
    InvalidRecoveryCodeError,
    SessionDecryptionError,
    BackupNotFoundError,
    PublicKeyMismatchError,
    CacheError,
    KeyManagementError,
)

__all__ = [
    # Main API
    "HybridDecryptionManager",
    "DecryptionStatistics",
    # Strategies
    "DecryptionStrategyInterface",
    "PersistentSessionStrategy",
    "ServerBackupStrategy",
    "ManualExportStrategy",
    # Crypto
    "RecoveryKeyDecoder",
    "SessionDecryptor",
    "MegolmExportDecryptor",
    # Key Management
    "MatrixKeyBackupManager",
    "ManualKeyLoader",
    # Cache
    "CacheInterface",
    "JSONFileCacheAdapter",
    "InMemoryCache",
    # Exceptions
    "DecryptionError",
    "InvalidRecoveryCodeError",
    "SessionDecryptionError",
    "BackupNotFoundError",
    "PublicKeyMismatchError",
    "CacheError",
    "KeyManagementError",
]
