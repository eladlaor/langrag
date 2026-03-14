"""
Download and manage Matrix server-side key backups.

This module handles:
1. Fetching backup version info from the server
2. Downloading all backed up keys
3. Decrypting keys using the recovery code
4. Caching keys locally for performance
5. Merging with existing keys

API Endpoints (Matrix Client-Server API v3):
- GET /room_keys/version -> backup metadata
- GET /room_keys/keys?version={v} -> all backed up keys

Reference:
- https://spec.matrix.org/latest/client-server-api/#server-side-key-backups
"""

import logging
from typing import Any
import aiohttp

from core.ingestion.decryption.crypto import RecoveryKeyDecoder, SessionDecryptor
from core.ingestion.decryption.exceptions import (
    SessionDecryptionError,
    BackupNotFoundError,
)
from core.ingestion.decryption.cache.base import CacheInterface
from constants import HEADER_AUTHORIZATION, AUTH_BEARER_PREFIX
from custom_types.field_keys import DecryptionResultKeys

logger = logging.getLogger(__name__)


class MatrixKeyBackupManager:
    """
    Manager for Matrix server-side key backups.

    Downloads encrypted keys from the Matrix homeserver, decrypts them
    using the recovery code, and caches them locally.

    Usage:
        manager = MatrixKeyBackupManager(
            homeserver="https://matrix.beeper.com",
            access_token="...",
            recovery_code="EsTs Uqkz...",
        )
        keys = await manager.sync_keys()
    """

    def __init__(
        self,
        homeserver: str,
        access_token: str,
        recovery_code: str,
        cache: CacheInterface,
    ):
        """
        Initialize the key backup manager.

        Args:
            homeserver: Matrix homeserver URL (e.g., "https://matrix.beeper.com")
            access_token: Matrix access token for authentication
            recovery_code: Base58-encoded recovery code
            cache: Cache implementation for storing decrypted keys

        Raises:
            InvalidRecoveryCodeError: If the recovery code is malformed
        """
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self.cache = cache

        # Decode recovery code to get private key
        decoder = RecoveryKeyDecoder()
        self._recovery_key = decoder.decode(recovery_code)
        self._decryptor = SessionDecryptor(self._recovery_key)

        # Backup metadata (populated on first sync)
        self.backup_version: str | None = None
        self.backup_public_key: str | None = None
        self.backup_key_count: int | None = None

    async def sync_keys(self) -> list[dict[str, Any]]:
        """
        Sync keys from server-side backup.

        Downloads all keys from the server, decrypts them, and merges
        with any existing cached keys.

        Returns:
            List of decrypted session key dicts, each containing:
            - room_id: str
            - session_id: str
            - algorithm: str
            - sender_key: str
            - session_key: str
            - forwarding_curve25519_key_chain: list

        Raises:
            BackupNotFoundError: If no backup exists on the server
        """
        # Get backup version info
        version_info = await self._fetch_backup_version()

        if not version_info:
            raise BackupNotFoundError("No server-side backup found. " "Enable backup in your Matrix client (Beeper) to use this feature.")

        self.backup_version = version_info.get("version")
        self.backup_public_key = version_info.get("auth_data", {}).get("public_key")
        self.backup_key_count = version_info.get("count", 0)

        logger.info(f"Found backup v{self.backup_version} with {self.backup_key_count} keys")

        # Fetch all backed up keys
        raw_keys = await self._fetch_all_backed_up_keys()

        # Decrypt each session
        decrypted_keys = []
        success_count = 0
        failed_count = 0

        rooms = raw_keys.get("rooms", {})
        for room_id, room_data in rooms.items():
            sessions = room_data.get("sessions", {})
            for session_id, session_info in sessions.items():
                try:
                    session_data = session_info.get("session_data", {})
                    decrypted = self._decryptor.decrypt(session_data)

                    # Add room_id and session_id to the decrypted data
                    decrypted[DecryptionResultKeys.ROOM_ID] = room_id
                    decrypted[DecryptionResultKeys.SESSION_ID] = session_id

                    decrypted_keys.append(decrypted)
                    success_count += 1

                except SessionDecryptionError as e:
                    logger.debug(f"Failed to decrypt session {room_id}/{session_id}: {e}")
                    failed_count += 1

        logger.info(f"Decrypted {success_count} keys successfully " f"({failed_count} failed)")

        # Merge with existing cache
        merged_keys = self.cache.merge(decrypted_keys)

        return merged_keys

    async def _fetch_backup_version(self) -> dict[str, Any] | None:
        """
        Fetch backup version info from the server.

        Returns:
            Backup version info dict or None if no backup exists
        """
        url = f"{self.homeserver}/_matrix/client/v3/room_keys/version"
        headers = {
            HEADER_AUTHORIZATION: f"{AUTH_BEARER_PREFIX} {self.access_token}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 404:
                        logger.warning("No backup version found (404)")
                        return None

                    if response.status == 401:
                        error_text = await response.text()
                        raise PermissionError(f"Authentication failed: {error_text}")

                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientError as e:
            logger.error(f"Failed to fetch backup version: {e}")
            raise

    async def _fetch_all_backed_up_keys(self) -> dict[str, Any]:
        """
        Fetch all backed up keys from the server.

        Returns:
            Dict containing rooms and their sessions
        """
        if not self.backup_version:
            raise RuntimeError("Must fetch backup version first")

        url = f"{self.homeserver}/_matrix/client/v3/room_keys/keys"
        headers = {
            HEADER_AUTHORIZATION: f"{AUTH_BEARER_PREFIX} {self.access_token}",
        }
        params = {
            "version": self.backup_version,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 404:
                        logger.warning("No keys found in backup (404)")
                        return {"rooms": {}}

                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientError as e:
            logger.error(f"Failed to fetch backup keys: {e}")
            raise

    def get_cached_keys(self) -> list[dict[str, Any]]:
        """
        Get keys from local cache without re-syncing.

        Returns:
            List of cached key dictionaries, or empty list if no cache exists
        """
        return self.cache.load()

    def get_keys_for_room(self, room_id: str) -> list[dict[str, Any]]:
        """
        Get cached keys for a specific room.

        Args:
            room_id: Matrix room ID

        Returns:
            List of keys for the specified room
        """
        all_keys = self.cache.load()
        return [key for key in all_keys if key.get(DecryptionResultKeys.ROOM_ID) == room_id]

    def get_key_for_session(
        self,
        room_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """
        Get a specific key by room and session ID.

        Args:
            room_id: Matrix room ID
            session_id: Megolm session ID

        Returns:
            Key dict or None if not found
        """
        all_keys = self.cache.load()
        for key in all_keys:
            if key.get(DecryptionResultKeys.ROOM_ID) == room_id and key.get(DecryptionResultKeys.SESSION_ID) == session_id:
                return key
        return None
