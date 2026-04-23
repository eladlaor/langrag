from datetime import datetime, UTC
import logging
import os

from typing import Any
from collections.abc import Callable
from pathlib import Path
import sqlite3
import asyncio

import json
import httpx
from core.ingestion.extractors.base import RawDataExtractorInterface
from nio import AsyncClient, AsyncClientConfig

from config import get_settings
from constants import (
    CACHE_FILENAME_CHAT_ROOM_MAPPING,
    TIMEOUT_HTTP_REQUEST,
    MatrixEventType,
    MatrixEncryptionAlgorithm,
    DEFAULT_BEEPER_MATRIX_STORE_PATH,
    DEFAULT_SERVER_BACKUP_KEYS_PATH,
    DEFAULT_EXPORTED_KEYS_PATH,
    DOCKER_DATA_MOUNT_PATH,
    DIR_NAME_ENCRYPTED_MESSAGES,
    DIR_NAME_DECRYPTED_MESSAGES,
    DayBoundary,
    DATE_FORMAT_ISO,
    HEADER_AUTHORIZATION,
    AUTH_BEARER_PREFIX,
    WHATSAPP_EVENT_TYPE_FILTERS,
    BRIDGE_MESSAGE_TYPES,
    MATRIX_KEY_RELATES_TO,
    MESSAGING_PLATFORM_WHATSAPP,
    EXTRACTION_STRATEGY_GROUP_CHAT,
    DecryptionMethod,
    POLL_START_CONTENT_KEY,
    POLL_RESPONSE_CONTENT_KEY,
)
from custom_types.exceptions import ConfigurationError
from custom_types.field_keys import DecryptionResultKeys, DiscussionKeys

# Import decryption components from new architecture
from core.ingestion.decryption import (
    HybridDecryptionManager,
    PersistentSessionStrategy,
    ServerBackupStrategy,
    ManualExportStrategy,
    MatrixKeyBackupManager,
    JSONFileCacheAdapter,
    InvalidRecoveryCodeError,
)

# Configuring logger for this module
logger = logging.getLogger(__name__)


# =============================================================================
# LAZY INITIALIZATION HELPERS
# =============================================================================
# Deferring environment variable validation to runtime (not import time)
# Enabling importing the module for testing without requiring credentials

_cached_access_token: str | None = None
_cached_decrypted_keys_path: str | None = None


def _get_access_token() -> str:
    """
    Getting Beeper access token with lazy initialization.

    Raises:
        ConfigurationError: If BEEPER_ACCESS_TOKEN is not set
    """
    global _cached_access_token
    if _cached_access_token is None:
        _cached_access_token = os.getenv("BEEPER_ACCESS_TOKEN")
        if not _cached_access_token:
            raise ConfigurationError("BEEPER_ACCESS_TOKEN is not set. " "Set it in .env or run: python src/cli/beeper_setup/extract_beeper_access_token.py")
    return _cached_access_token


def _get_decrypted_keys_path() -> str:
    """
    Getting decrypted keys file path with lazy initialization.

    Raises:
        ConfigurationError: If DECRYPTED_KEYS_FILE_PATH is not set
    """
    global _cached_decrypted_keys_path
    if _cached_decrypted_keys_path is None:
        _cached_decrypted_keys_path = os.getenv("DECRYPTED_KEYS_FILE_PATH")
        if not _cached_decrypted_keys_path:
            raise ConfigurationError("DECRYPTED_KEYS_FILE_PATH is not set. " "Set it in .env (default: /app/secrets/decrypted-keys.json)")
    return _cached_decrypted_keys_path


def _get_beeper_settings():
    """Getting Beeper settings from config (lazy)."""
    return get_settings().beeper


def _get_headers() -> dict[str, str]:
    """Getting authorization headers with lazy token loading."""
    return {HEADER_AUTHORIZATION: f"{AUTH_BEARER_PREFIX} {_get_access_token()}"}


def _get_base_url() -> str:
    """Getting Beeper base URL from settings."""
    return _get_beeper_settings().base_url


# Calculating base output directory (relative to project root)
# Project structure: src/core/ingestion/extractors/beeper.py
# Project root is 4 levels up from this file
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
base_output_dir = str(_PROJECT_ROOT / "output")


def _run_async_extraction_in_process(source_name, kwargs_dict):
    """
    Module-level function for multiprocessing.
    Running async extraction in separate process with fresh event loop.

    This function is at module level to be pickle-able for multiprocessing.spawn.
    """
    try:
        # CRITICAL: Resetting global database connection to avoid event loop conflicts
        # The Motor client from parent process is tied to parent's event loop
        import db.connection as db_conn

        db_conn._client = None
        db_conn._database = None

        # Creating a fresh extractor instance in this new process
        extractor = RawDataExtractorBeeper(source_name=source_name)

        # Running the async method with a fresh event loop (no uvloop conflicts)
        result_path = asyncio.run(extractor._extract_whatsapp_group_chat_messages_async(**kwargs_dict))
        return {"success": True, "result": result_path}
    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# Module-level lock to serialize Beeper session refresh across concurrent API requests.
# SQLite (used by matrix-nio for the encryption store) does not handle concurrent writers,
# so parallel orchestrator runs must take turns refreshing the session.
_session_refresh_lock = asyncio.Lock()


class RawDataExtractorBeeper(RawDataExtractorInterface):
    # Defining as class variable with default empty dict
    EXTRACTION_STRATEGIES_MAP: dict[str, dict[str, Callable]] = {}

    CHAT_NAME_TO_ROOM_ID_CACHE_PATH: str = CACHE_FILENAME_CHAT_ROOM_MAPPING
    CHAT_NAME_TO_ROOM_ID_CACHE: dict[str, str] = {}

    def __init__(self, source_name, database=None, store_path_override=None, **kwargs):
        try:
            super().__init__(**kwargs)

            # Setting instance attributes
            self.source_name = source_name

            # NEW: Storing database reference for MongoDB cache
            self._database = database
            self._room_id_cache_repo = None
            self._mongodb_seeded_from_file = False

            # Matrix persistent session attributes
            beeper_settings = get_settings().beeper
            self.store_path = store_path_override or os.getenv("BEEPER_MATRIX_STORE_PATH", DEFAULT_BEEPER_MATRIX_STORE_PATH)
            self.homeserver = beeper_settings.base_url
            self.client = None  # Will be AsyncClient with persistent store
            self.beeper_email = os.getenv("BEEPER_EMAIL")

            # Populating the extraction strategies map
            # LangGraph 1.0: Using async version directly (no sync wrapper needed)
            self.EXTRACTION_STRATEGIES_MAP = {MESSAGING_PLATFORM_WHATSAPP: {EXTRACTION_STRATEGY_GROUP_CHAT: self._extract_whatsapp_group_chat_messages_async}}

            # Ensuring a valid cache path is set with a default in a persistent location
            cache_path = kwargs.get("chat_name_to_room_id_cache_path")
            if not cache_path:
                # Using environment variable or default to persistent data directory
                # In Docker: /app/examples/ is mounted as a volume for persistence
                cache_path = os.environ.get("BEEPER_ROOM_ID_CACHE_PATH")
                if not cache_path:
                    # Preferring /app/data if it exists (Docker), else use ./data relative to cwd
                    if os.path.isdir(DOCKER_DATA_MOUNT_PATH):
                        cache_path = f"{DOCKER_DATA_MOUNT_PATH}/{CACHE_FILENAME_CHAT_ROOM_MAPPING}"
                    else:
                        # Local development: using project's data directory
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
                        cache_path = os.path.join(project_root, "data", CACHE_FILENAME_CHAT_ROOM_MAPPING)

            self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH = cache_path
            logger.info(f"Room ID cache will be stored at: {cache_path}")
            self.CHAT_NAME_TO_ROOM_ID_CACHE = {}  # Initializing cache dict

            # Logging decryption keys file path (lazy-loaded)
            logging.info(f"Using decryption keys file: {_get_decrypted_keys_path()}")

        except Exception as e:
            error_message = f"Error initializing RawDataExtractorBeeper: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message)

    def _get_beeper_session_info(self):
        """
        Extracting session info from Beeper Desktop database.

        Returns:
            dict with user_id, device_id, access_token, homeserver or None if not found
        """
        beeper_db = Path.home() / ".config" / "BeeperTexts" / "account.db"

        if not beeper_db.exists():
            logging.warning(f"Beeper Desktop database not found at {beeper_db}")
            return None

        try:
            conn = sqlite3.connect(f"file:{beeper_db}?mode=ro", uri=True)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT user_id, device_id, access_token, homeserver
                FROM account
                LIMIT 1
            """)

            row = cursor.fetchone()
            conn.close()

            if row:
                user_id, device_id, access_token, homeserver = row
                logging.info(f"Found Beeper Desktop session for {user_id}")
                return {"user_id": user_id, "device_id": device_id, "access_token": access_token, "homeserver": homeserver}

            return None
        except Exception as e:
            logging.warning(f"Could not read Beeper database: {e}")
            return None

    async def _init_persistent_client(self) -> AsyncClient:
        """
        Initializing or resuming Matrix client session with persistent key storage.
        Keys are automatically loaded from store.

        Returns:
            AsyncClient instance with persistent store and encryption enabled
        """
        if self.client and hasattr(self.client, "logged_in") and self.client.logged_in:
            logging.info("Using existing Matrix session")
            return self.client

        logging.info("Initializing Matrix persistent session...")

        # Trying to get session info from Beeper Desktop
        beeper_info = self._get_beeper_session_info()

        if beeper_info:
            user_id = beeper_info["user_id"]
            device_id = beeper_info["device_id"]
            access_token = beeper_info["access_token"]
            homeserver = beeper_info["homeserver"].rstrip("/")  # Stripping trailing slash to avoid double slash in URLs
        else:
            # Falling back to environment variables
            logging.warning("Could not find Beeper Desktop session, using environment variables")

            access_token = os.getenv("BEEPER_ACCESS_TOKEN")
            if not access_token:
                raise RuntimeError("No valid session found. Either:\n" "  1. Log in to Beeper Desktop (recommended)\n" "  2. Run: .venv/bin/python src/cli/beeper_setup/extract_beeper_access_token.py\n" "  3. Or set BEEPER_ACCESS_TOKEN in .env manually")

            # Trying to derive user_id from .env
            if self.beeper_email:
                username = self.beeper_email.split("@")[0]
                user_id = f"@{username}:beeper.com"
            else:
                raise RuntimeError("BEEPER_EMAIL must be set in .env")

            homeserver = self.homeserver
            device_id = None  # Will be auto-assigned

        # Creating store directory if needed
        store_path = Path(self.store_path)
        store_path.mkdir(parents=True, exist_ok=True)

        # Creating client with persistent store
        config = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        )

        self.client = AsyncClient(homeserver=homeserver, user=user_id, store_path=str(store_path), config=config)

        # Setting credentials directly (already logged in via Beeper Desktop or .env)
        self.client.access_token = access_token
        self.client.user_id = user_id
        self.client.device_id = device_id  # Always setting, even if None (will be auto-assigned on first sync)

        logging.info(f"Session credentials loaded for {self.client.user_id}")

        # Trying to load existing store if it exists (gracefully handling if device_id not yet set)
        try:
            self.client.load_store()
            logging.info("Loaded existing encryption store")
        except Exception as e:
            logging.info(f"No existing store to load (this is normal for first run): {e}")

        # Always performing sync to:
        # 1. Auto-assigning device_id if None
        # 2. Initializing encryption if needed
        # 3. Receiving/updating encryption keys
        beeper_settings = get_settings().beeper
        logging.info("Syncing to initialize/update encryption keys...")
        await self.client.sync(timeout=beeper_settings.matrix_sync_timeout_ms, full_state=False)
        logging.info(f"Sync completed - device_id: {self.client.device_id}")

        return self.client

    async def refresh_session_via_login(self) -> None:
        """
        Creating a fresh Matrix session via direct password login.

        This method:
        1. Logging in with email/password from environment variables
        2. Creating a new encryption session with fresh keys
        3. Replacing the old session store with the new one

        This ensures the session is never stale and eliminates the need for
        manual intervention when encryption keys become out of sync.

        Raises:
            RuntimeError: If BEEPER_EMAIL or BEEPER_PASSWORD not set in environment
        """
        logging.info("Refreshing Matrix session via direct login (acquiring session lock)...")

        async with _session_refresh_lock:
            logging.info("Session lock acquired - proceeding with refresh")
            await self._refresh_session_impl()

    async def _refresh_session_impl(self) -> None:
        """Internal implementation of session refresh, called under _session_refresh_lock."""
        from nio import AsyncClient, AsyncClientConfig, LoginResponse
        from pathlib import Path
        import shutil

        # Getting credentials from environment
        email = os.getenv("BEEPER_EMAIL")
        password = os.getenv("BEEPER_PASSWORD")

        if not email or not password:
            raise RuntimeError("BEEPER_EMAIL and BEEPER_PASSWORD must be set in .env for automatic session refresh.\n" "Add these to your .env file:\n" "  BEEPER_EMAIL=your_email@example.com\n" "  BEEPER_PASSWORD=your_password")

        # Creating temporary store path
        temp_store_path = Path(f"{self.store_path}_temp")
        temp_store_path.mkdir(parents=True, exist_ok=True)

        try:
            # Creating client with fresh session
            config = AsyncClientConfig(
                store_sync_tokens=True,
                encryption_enabled=True,
            )

            client = AsyncClient(
                homeserver=self.homeserver.rstrip("/"),  # Removing trailing slash
                user=email,
                store_path=str(temp_store_path),
                config=config,
            )

            # Logging in with password
            response = await client.login(password, device_name="LangTalks Newsletter Bot")

            if not isinstance(response, LoginResponse):
                raise RuntimeError(f"Login failed: {response}")

            logging.info(f"Login successful - User: {response.user_id}, Device: {response.device_id}")

            # Performing initial sync to download encryption keys
            beeper_settings = get_settings().beeper
            logging.info("Syncing to initialize encryption keys...")
            await client.sync(timeout=beeper_settings.matrix_sync_timeout_ms, full_state=False)
            logging.info("Sync completed - encryption keys downloaded")

            # Closing the client
            await client.close()

            # Replacing old store with new one
            old_store = Path(self.store_path)
            if old_store.exists():
                backup_path = Path(f"{self.store_path}_backup")
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                shutil.move(str(old_store), str(backup_path))
                logging.info(f"Backed up old session to {backup_path}")

            shutil.move(str(temp_store_path), str(old_store))
            logging.info(f"Fresh session installed to {old_store}")

            # Resetting client so next call to _init_persistent_client will use new session
            self.client = None

        except Exception as e:
            # Cleaning up temp store on error
            if temp_store_path.exists():
                shutil.rmtree(temp_store_path)
            raise RuntimeError(f"Failed to refresh session: {e}")

    async def _get_all_messages_async(self, room_id, batch_size=None, max_messages=None, debug=False, include_all_events=False, include_whatsapp=True, include_encrypted=True):
        """
        Fetching messages from a room using AsyncClient (replaces synchronous REST API calls).

        Args:
            room_id: The room ID to fetch messages from
            batch_size: Number of messages to fetch per request
            max_messages: Maximum number of messages to fetch (None for all)
            debug: Whether to print debug information
            include_all_events: Including all event types, not just messages
            include_whatsapp: Including WhatsApp-specific event types
            include_encrypted: Including encrypted message events

        Returns:
            List of message events
        """
        # Ensuring client is initialized
        client = await self._init_persistent_client()
        beeper_settings = get_settings().beeper
        batch_size = batch_size or beeper_settings.message_batch_size

        try:
            if max_messages:
                logging.info(f"Will fetch up to {max_messages} latest {'events' if include_all_events else 'messages'}")
            else:
                logging.info(f"Fetching all {'events' if include_all_events else 'messages'} (this might take a while)...")

            messages = []
            next_token = None
            total_batches = 0

            # Message types to include
            message_types = [MatrixEventType.ROOM_MESSAGE]
            if include_whatsapp:
                message_types.extend(BRIDGE_MESSAGE_TYPES)
            if include_encrypted:
                message_types.append(MatrixEventType.ROOM_ENCRYPTED)
            message_types.append(MatrixEventType.POLL_RESPONSE)

            if debug:
                logging.debug(f"Looking for event types: {message_types}")

            while True:
                # Fetching a batch of messages using AsyncClient
                response = await client.room_messages(
                    room_id=room_id,
                    start=next_token,
                    limit=batch_size,
                    direction="b",  # backwards (most recent first)
                )

                # Checking if response is an error
                from nio import RoomMessagesError

                if isinstance(response, RoomMessagesError):
                    # Log all attributes of the error for debugging
                    error_attrs = {k: v for k, v in response.__dict__.items() if not k.startswith("_")}
                    logging.error(f"RoomMessagesError attributes: {error_attrs}")
                    error_msg = f"Error fetching messages from room {room_id}: {response.message} (status: {response.status_code})"
                    logging.error(error_msg)
                    raise RuntimeError(error_msg)

                # Debug: Print raw data before filtering
                if debug:
                    logging.debug("\n--- Raw API Response Data ---")
                    chunk = response.chunk
                    logging.debug(f"Total events in chunk: {len(chunk)}")
                    if chunk:
                        event_types = set(event.type for event in chunk)
                        logging.debug(f"Event types in this batch: {event_types}")

                chunk = response.chunk

                # Filtering events based on flags
                if include_all_events:
                    filtered_events = chunk
                else:
                    # Filtering for messages including WhatsApp-specific types
                    # Safely getting event type - some events have 'type', others have 'event_type', others are in source
                    def get_event_type(event):
                        if hasattr(event, "type"):
                            return event.type
                        elif hasattr(event, "event_type"):
                            return event.event_type
                        elif hasattr(event, "source") and isinstance(event.source, dict):
                            return event.source.get("type")
                        return None

                    filtered_events = [event for event in chunk if get_event_type(event) in message_types]

                    # Extra debugging for WhatsApp events
                    if debug and include_whatsapp:
                        whatsapp_events = [event for event in chunk if get_event_type(event) and any(whatsapp_type in get_event_type(event) for whatsapp_type in WHATSAPP_EVENT_TYPE_FILTERS)]
                        if whatsapp_events:
                            logging.debug(f"Found {len(whatsapp_events)} potential WhatsApp-related events")

                if filtered_events:
                    messages.extend(filtered_events)
                    total_batches += 1
                    # Only log every 10 batches to reduce noise
                    if total_batches % 10 == 0 or total_batches == 1:
                        logging.info(f"Batch {total_batches}: Found {len(filtered_events)} {'events' if include_all_events else 'messages'}. Total: {len(messages)}")
                else:
                    # Only logging if debugging
                    if debug:
                        logging.debug(f"Batch {total_batches + 1}: No {'events' if include_all_events else 'message events'} found in this batch")
                        if chunk:
                            logging.debug(f"(But there were {len(chunk)} other events in this batch)")

                # Checking if we've reached our message limit
                if max_messages and len(messages) >= max_messages:
                    logging.info(f"Reached limit of {max_messages} {'events' if include_all_events else 'messages'}")
                    # Trimming to exactly max_messages if we went over
                    messages = messages[:max_messages]
                    break

                # Getting the next token
                next_token = response.end
                if not next_token:
                    logging.info("Reached the end of the message history")
                    break

                # Waiting to be nice to the server
                await asyncio.sleep(beeper_settings.async_sleep_delay_seconds)

            return messages

        except Exception as e:
            error_message = f"Error fetching messages from room {room_id}: {e}"
            logging.error(error_message)
            raise RuntimeError(error_message)

    def _event_to_dict(self, event, room_id: str) -> dict:
        """
        Converting matrix-nio RoomMessage event to dictionary format.

        Args:
            event: RoomMessage event from matrix-nio
            room_id: The room ID where this event occurred

        Returns:
            Dictionary representation of the event
        """
        result = {DecryptionResultKeys.EVENT_ID: event.event_id, DecryptionResultKeys.SENDER: event.sender, DecryptionResultKeys.ORIGIN_SERVER_TS: event.server_timestamp, DecryptionResultKeys.TYPE: event.type if hasattr(event, "type") else MatrixEventType.ROOM_MESSAGE, DecryptionResultKeys.ROOM_ID: room_id, DecryptionResultKeys.CONTENT: {}}

        # Handling encrypted events
        if hasattr(event, "ciphertext"):
            result[DecryptionResultKeys.TYPE] = MatrixEventType.ROOM_ENCRYPTED
            result[DecryptionResultKeys.CONTENT] = {"algorithm": event.algorithm if hasattr(event, "algorithm") else MatrixEncryptionAlgorithm.MEGOLM_V1_AES_SHA2, "ciphertext": event.ciphertext, "sender_key": event.sender_key, DecryptionResultKeys.SESSION_ID: event.session_id, "device_id": event.device_id if hasattr(event, "device_id") else None}
        # Handling decrypted/regular message events
        elif hasattr(event, "body"):
            result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.BODY] = event.body
            if hasattr(event, "msgtype"):
                result[DecryptionResultKeys.CONTENT][DecryptionResultKeys.MSGTYPE] = event.msgtype

        # Copying any additional attributes that might exist
        if hasattr(event, "source"):
            # source contains the raw event dict from server
            source = event.source
            if isinstance(source, dict):
                source_content = source.get(DecryptionResultKeys.CONTENT, {})

                # Preserving m.relates_to if present (critical for reply threading and poll vote linking)
                if MATRIX_KEY_RELATES_TO in source_content:
                    result[DecryptionResultKeys.CONTENT][MATRIX_KEY_RELATES_TO] = source_content[MATRIX_KEY_RELATES_TO]

                # Preserving poll-specific content keys from MSC3381
                for poll_key in (POLL_START_CONTENT_KEY, POLL_RESPONSE_CONTENT_KEY):
                    if poll_key in source_content:
                        result[DecryptionResultKeys.CONTENT][poll_key] = source_content[poll_key]

                # Copying any other important fields
                for key in ["unsigned", "age"]:
                    if key in source:
                        result[key] = source[key]

        return result

    async def _get_decryption_manager(self) -> HybridDecryptionManager:
        """
        Creating and initializing a HybridDecryptionManager with all available strategies.

        Strategy order (by priority):
        1. PersistentSessionStrategy - Using matrix-nio AsyncClient's olm machine (fastest, for recent messages)
        2. ServerBackupStrategy - Downloading keys from Matrix server backup (if BEEPER_RECOVERY_CODE set)
        3. ManualExportStrategy - Using manually exported keys (fallback for older messages)

        Returns:
            Initialized HybridDecryptionManager ready for decryption

        Raises:
            RuntimeError: If no decryption strategies could be initialized
        """
        strategies = []

        # Strategy 1: Persistent Session (for recent messages synced through client)
        try:
            client = await self._init_persistent_client()
            if client and client.olm:
                strategies.append(PersistentSessionStrategy(client))
                logging.debug("Added PersistentSessionStrategy")
            else:
                logging.warning("Client has no olm machine - persistent session strategy disabled")
        except Exception as e:
            logging.warning(f"Could not initialize PersistentSessionStrategy: {e}")

        # Strategy 2: Server Backup (if BEEPER_RECOVERY_CODE is set)
        recovery_code = os.getenv("BEEPER_RECOVERY_CODE")
        if recovery_code:
            try:
                logging.info("Setting up server backup strategy...")
                cache = JSONFileCacheAdapter(Path(DEFAULT_SERVER_BACKUP_KEYS_PATH))
                key_manager = MatrixKeyBackupManager(
                    homeserver=self.homeserver,
                    access_token=os.getenv("BEEPER_ACCESS_TOKEN"),
                    recovery_code=recovery_code,
                    cache=cache,
                )
                strategies.append(ServerBackupStrategy(key_manager))
                logging.debug("Added ServerBackupStrategy")
            except InvalidRecoveryCodeError as e:
                logging.warning(f"Invalid recovery code: {e}")
                logging.warning("   Check BEEPER_RECOVERY_CODE in your .env file")
            except Exception as e:
                logging.warning(f"Could not initialize ServerBackupStrategy: {e}")
        else:
            logging.debug("BEEPER_RECOVERY_CODE not set, skipping ServerBackupStrategy")

        # Strategy 3: Manual Export (fallback for past messages)
        # Always prefer fresh decryption from element-keys.txt to avoid stale cached keys
        exported_keys_path = Path(DEFAULT_EXPORTED_KEYS_PATH)
        export_password = os.getenv("BEEPER_EXPORT_PASSWORD")
        if exported_keys_path.exists() and export_password:
            try:
                strategies.append(ManualExportStrategy(keys_file_path=str(exported_keys_path), passphrase=export_password))
                logging.debug("Added ManualExportStrategy (fresh decrypt from element-keys.txt)")
            except Exception as e:
                logging.warning(f"Could not initialize ManualExportStrategy from element-keys.txt: {e}")
        else:
            # Fall back to pre-decrypted keys if element-keys.txt or password unavailable
            decrypted_keys_path = _get_decrypted_keys_path()
            if os.path.exists(decrypted_keys_path):
                try:
                    strategies.append(
                        ManualExportStrategy(
                            keys_file_path=decrypted_keys_path,
                            passphrase=None,  # Already decrypted
                        )
                    )
                    logging.debug("Added ManualExportStrategy (cached decrypted-keys.json)")
                except Exception as e:
                    logging.warning(f"Could not initialize ManualExportStrategy: {e}")
            else:
                logging.debug("No manual export keys found")

        if not strategies:
            raise RuntimeError("No decryption strategies available. " "Set BEEPER_RECOVERY_CODE or export keys to enable decryption.")

        # Creating and initializing manager
        manager = HybridDecryptionManager(strategies)
        await manager.initialize()

        logging.info(f"Decryption manager initialized with {len(strategies)} strategies: {manager.get_strategy_names()}")
        return manager

    async def _extract_whatsapp_group_chat_messages_async(self, **kwargs) -> str:
        """
        Extracting and decrypting messages using persistent session (NEW APPROACH).
        No manual key export needed!

        Using MongoDB cache by default (MongoDB-first architecture).
        Falling back to file-based cache if ENABLE_FILE_CACHE flag is enabled.

        Args:
            output_dir: Base output directory for messages
            groupchat_name: Name of the WhatsApp group
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            force_refresh: If True, bypassing cache and re-extracting from Beeper

        Returns:
            Path to the decrypted messages file
        """
        try:
            base_output_dir = kwargs.get("output_dir")
            if not base_output_dir:
                raise ValueError("output_dir is required")

            encrypted_messages_dir_path = os.path.join(base_output_dir, DIR_NAME_ENCRYPTED_MESSAGES)
            decrypted_messages_dir_path = os.path.join(base_output_dir, DIR_NAME_DECRYPTED_MESSAGES)

            # Creating directories for encrypted and decrypted messages
            os.makedirs(encrypted_messages_dir_path, exist_ok=True)
            os.makedirs(decrypted_messages_dir_path, exist_ok=True)

            room_name: str = kwargs.get("groupchat_name")
            if not room_name:
                raise ValueError("groupchat_name is required")

            start_date_str: str = kwargs.get("start_date")
            if not start_date_str:
                raise ValueError("start_date is required")

            try:
                datetime.strptime(start_date_str, DATE_FORMAT_ISO)
            except ValueError:
                raise ValueError(f"start_date '{start_date_str}' must be in format YYYY-MM-DD")

            end_date_str: str = kwargs.get("end_date")
            if not end_date_str:
                raise ValueError("end_date is required")

            logging.info(f"Extracting messages from beeper, room: {room_name}, from {start_date_str} to {end_date_str}")

            try:
                datetime.strptime(end_date_str, DATE_FORMAT_ISO)
            except ValueError:
                raise ValueError(f"end_date '{end_date_str}' must be in format YYYY-MM-DD")

            force_refresh = kwargs.get("force_refresh", False)

            # MongoDB cache check (MongoDB-first architecture)
            from config import get_settings
            from db.connection import get_database
            from db.repositories.extraction_cache import ExtractionCacheRepository

            settings = get_settings()

            # Generating cache key
            db = await get_database()
            cache_repo = ExtractionCacheRepository(db)
            cache_key = cache_repo.generate_cache_key(room_name, start_date_str, end_date_str)

            # Checking MongoDB cache first (unless force_refresh)
            if not force_refresh and not settings.database.enable_file_cache:
                # Fast path: exact cache key match
                logging.info(f"Checking MongoDB cache: {cache_key}")
                cached_extraction = await cache_repo.get_cached_extraction(cache_key)

                if cached_extraction:
                    # Exact cache hit — use cached messages directly
                    decrypted_messages = cached_extraction.get(DiscussionKeys.MESSAGES, [])
                    logging.info(f"MongoDB cache hit (exact): {len(decrypted_messages)} messages " f"(cached at {cached_extraction.get('created_at')})")

                    safe_room_name = room_name.replace(" ", "_").replace("/", "_")
                    start_date_formatted = start_date_str.replace("-", "")
                    decrypted_messages_file_path = os.path.join(decrypted_messages_dir_path, f"decrypted_{safe_room_name}_{start_date_formatted}.json")

                    output_dir = os.path.dirname(decrypted_messages_file_path)
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)

                    with open(decrypted_messages_file_path, "w") as f:
                        json.dump(decrypted_messages, f, indent=2, ensure_ascii=False)

                    logging.info(f"Wrote cached messages to file for debugging: {decrypted_messages_file_path}")
                    return decrypted_messages_file_path

                # Slow path: overlap-aware cache check
                # Find cached extractions that overlap with the requested date range
                overlapping = await cache_repo.get_overlapping_extractions(room_name, start_date_str, end_date_str)

                if overlapping:
                    # Check if any single cached extraction is a SUPERSET of the requested range
                    for cached_doc in overlapping:
                        if cached_doc["start_date"] <= start_date_str and cached_doc["end_date"] >= end_date_str:
                            # Superset found — filter messages by requested timestamp range
                            from custom_types.field_keys import DecryptionResultKeys as DRKeys
                            all_cached_msgs = cached_doc.get(DiscussionKeys.MESSAGES, [])

                            req_start_ts = self._parse_timestamp(start_date_str, day_boundary="start")
                            req_end_ts = self._parse_timestamp(end_date_str, day_boundary=DayBoundary.END)

                            filtered = [
                                msg for msg in all_cached_msgs
                                if req_start_ts <= msg.get(DRKeys.ORIGIN_SERVER_TS, 0) <= req_end_ts
                            ]

                            logging.info(
                                f"✓ MongoDB cache hit (superset): filtered {len(filtered)}/{len(all_cached_msgs)} messages "
                                f"from cached range [{cached_doc['start_date']} to {cached_doc['end_date']}]"
                            )

                            safe_room_name = room_name.replace(" ", "_").replace("/", "_")
                            start_date_formatted = start_date_str.replace("-", "")
                            decrypted_messages_file_path = os.path.join(decrypted_messages_dir_path, f"decrypted_{safe_room_name}_{start_date_formatted}.json")

                            output_dir = os.path.dirname(decrypted_messages_file_path)
                            if output_dir:
                                os.makedirs(output_dir, exist_ok=True)

                            with open(decrypted_messages_file_path, "w") as f:
                                json.dump(filtered, f, indent=2, ensure_ascii=False)

                            # Cache the filtered result under the new exact key for future fast-path hits
                            try:
                                extraction_metadata = {
                                    "extracted_at": datetime.now(UTC).isoformat(),
                                    "source": "overlap_cache_superset_filter",
                                    "source_cache_key": cached_doc.get("cache_key"),
                                }
                                await cache_repo.set_cached_extraction(
                                    cache_key=cache_key, chat_name=room_name, room_id=cached_doc.get(DecryptionResultKeys.ROOM_ID, ""),
                                    start_date=start_date_str, end_date=end_date_str,
                                    messages=filtered, extraction_metadata=extraction_metadata,
                                )
                            except Exception as e:
                                logging.warning(f"Failed to cache filtered superset result: {e}")

                            return decrypted_messages_file_path

                    # No single superset — collect messages from all overlapping caches
                    # and remember which date ranges are already covered
                    from custom_types.field_keys import DecryptionResultKeys as DRKeys
                    cached_messages_by_event_id: dict[str, dict] = {}

                    for cached_doc in overlapping:
                        for msg in cached_doc.get(DiscussionKeys.MESSAGES, []):
                            event_id = msg.get(DRKeys.EVENT_ID)
                            if event_id:
                                cached_messages_by_event_id[event_id] = msg

                    if cached_messages_by_event_id:
                        logging.info(
                            f"Overlap cache: collected {len(cached_messages_by_event_id)} unique messages "
                            f"from {len(overlapping)} overlapping cache entries"
                        )
                        # Store for use after fresh extraction to merge with delta
                        kwargs["_overlap_cached_messages"] = cached_messages_by_event_id

            room_id = await self._get_room_id_with_cache(room_name)

            safe_room_name = room_name.replace(" ", "_").replace("/", "_")
            # Using date format instead of timestamp for consistency
            start_date_formatted = start_date_str.replace("-", "")

            # Initializing persistent client (keys auto-loaded)
            await self._init_persistent_client()

            encrypted_messages_file_path = os.path.join(encrypted_messages_dir_path, f"encrypted_{safe_room_name}_{start_date_formatted}.json")
            logging.info(f"Saving encrypted messages to: {encrypted_messages_file_path}")

            # Fetching messages using async client
            if not os.path.exists(encrypted_messages_file_path):
                logging.info("Fetching encrypted messages using persistent session...")
                encrypted_events = await self._get_all_messages_async(room_id, include_encrypted=True)

                # Converting nio events to dicts
                encrypted_messages = [self._event_to_dict(event, room_id) for event in encrypted_events]

                with open(encrypted_messages_file_path, "w") as f:
                    json.dump(encrypted_messages, f, indent=2)

                logging.info(f"Saved {len(encrypted_messages)} encrypted messages to {encrypted_messages_file_path}")
            else:
                # Loading existing encrypted messages
                with open(encrypted_messages_file_path) as f:
                    encrypted_messages = json.load(f)
                logging.info(f"Loaded {len(encrypted_messages)} encrypted messages from cache")

            decrypted_messages_file_path = os.path.join(decrypted_messages_dir_path, f"decrypted_{safe_room_name}_{start_date_formatted}.json")

            logging.info("Decrypting messages using persistent session keys...")
            logging.info(f"Will save decrypted messages to: {decrypted_messages_file_path}")

            # Parsing timestamps
            start_ts = self._parse_timestamp(start_date_str, day_boundary="start")
            end_ts = self._parse_timestamp(end_date_str, day_boundary=DayBoundary.END)

            logging.info(f"Date range: {datetime.fromtimestamp(start_ts/1000, tz=UTC).strftime('%Y-%m-%d %H:%M:%S')} to {datetime.fromtimestamp(end_ts/1000, tz=UTC).strftime('%Y-%m-%d %H:%M:%S')}")

            # Filtering messages by room_id and timestamp
            filtered_messages = [msg for msg in encrypted_messages if msg.get(DecryptionResultKeys.ROOM_ID) == room_id and start_ts <= msg.get(DecryptionResultKeys.ORIGIN_SERVER_TS, 0) <= end_ts]

            logging.info(f"Found {len(filtered_messages)} messages in room {room_id} within the specified date range")
            encrypted_count = len([m for m in filtered_messages if m.get("type") == MatrixEventType.ROOM_ENCRYPTED])
            logging.info(f"Of these, {encrypted_count} are encrypted")

            # Initializing HybridDecryptionManager with all available strategies
            decryption_manager = await self._get_decryption_manager()

            # Decrypting each message using the manager
            decrypted_messages = []
            for msg in filtered_messages:
                decrypted_msg = await decryption_manager.decrypt_message(msg, room_id)
                if decrypted_msg:
                    # Manager returns decrypted message
                    decrypted_messages.append(decrypted_msg)
                else:
                    # Message was not encrypted or couldn't be decrypted
                    decrypted_messages.append(msg)

            # Getting statistics from the manager
            stats = decryption_manager.get_statistics()
            logging.info(f"Successfully decrypted {stats['total_successes']}/{encrypted_count} messages")
            for strategy_name, count in stats["strategy_successes"].items():
                logging.info(f"   - {strategy_name}: {count}")

            # FAIL-FAST: If we have encrypted messages but couldn't decrypt ANY, provide clear instructions
            if encrypted_count > 0 and stats["total_successes"] == 0:
                error_message = (
                    f"\n{'='*70}\n"
                    f"DECRYPTION FAILED: Could not decrypt {encrypted_count} encrypted messages\n"
                    f"{'='*70}\n\n"
                    f"These messages are from {start_date_str} to {end_date_str}.\n\n"
                    f"To decrypt PAST messages, you need to export encryption keys:\n\n"
                    f"ONE-TIME SETUP (2 steps):\n\n"
                    f"1. EXPORT KEYS from Beeper Web UI:\n"
                    f"   a. Open https://app.beeper.com in your browser\n"
                    f"   b. Click profile icon → All Settings → Security & Privacy\n"
                    f"   c. Scroll to 'Encryption' → Click 'Export E2E room keys'\n"
                    f"   d. Set a password and download the file\n"
                    f"   e. Save to: {DEFAULT_EXPORTED_KEYS_PATH}\n\n"
                    f"2. ADD PASSWORD to .env:\n"
                    f"   BEEPER_EXPORT_PASSWORD=<your_export_password>\n\n"
                    f"3. Try your extraction again (decryption is now automatic!)\n\n"
                    f"Detailed guide: knowledge/beeper/HOW_TO_EXPORT_KEYS.md\n\n"
                    f"NOTE: This is a ONE-TIME step for past messages.\n"
                    f"   Future messages will decrypt automatically.\n"
                    f"{'='*70}\n"
                )
                logging.error(error_message)
                raise RuntimeError(f"Decryption failed: 0/{encrypted_count} messages decrypted. " f"See log above for step-by-step instructions to export encryption keys.")

            # PARTIAL SUCCESS: Some messages couldn't be decrypted
            elif encrypted_count > 0 and stats["total_successes"] < encrypted_count:
                failed_count = encrypted_count - stats["total_successes"]
                logging.warning(f"\nPARTIAL DECRYPTION: {failed_count}/{encrypted_count} messages could not be decrypted.\n" f"   This might be normal if:\n" f"   - Some messages are from before you joined the room\n" f"   - Some messages are from devices that never shared keys\n" f"   - Some encryption sessions expired\n")

            # Merge with overlap-cached messages if available
            # Fresh decryptions take priority over cached versions (in case of re-encrypted messages)
            overlap_cached = kwargs.get("_overlap_cached_messages")
            if overlap_cached:
                fresh_event_ids = {msg.get(DecryptionResultKeys.EVENT_ID) for msg in decrypted_messages if msg.get(DecryptionResultKeys.EVENT_ID)}
                merged_from_cache = 0
                for event_id, cached_msg in overlap_cached.items():
                    if event_id not in fresh_event_ids:
                        # Only include cached messages that fall within the requested date range
                        msg_ts = cached_msg.get(DecryptionResultKeys.ORIGIN_SERVER_TS, 0)
                        if start_ts <= msg_ts <= end_ts:
                            decrypted_messages.append(cached_msg)
                            merged_from_cache += 1

                if merged_from_cache > 0:
                    logging.info(f"Merged {merged_from_cache} messages from overlap cache into fresh extraction")

            # Sorting by timestamp
            decrypted_messages.sort(key=lambda msg: msg.get(DecryptionResultKeys.ORIGIN_SERVER_TS, 0))

            # Ensuring output directory exists
            output_dir = os.path.dirname(decrypted_messages_file_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                logging.info(f"Ensuring output directory exists: {output_dir}")

            # Writing to output file
            logging.info(f"Writing {len(decrypted_messages)} decrypted messages to {decrypted_messages_file_path}")
            with open(decrypted_messages_file_path, "w") as f:
                json.dump(decrypted_messages, f, indent=2, ensure_ascii=False)

            logging.info(f"Decrypted messages saved to {decrypted_messages_file_path}")

            # Saving to MongoDB cache (MongoDB-first architecture)
            if not settings.database.enable_file_cache:
                try:
                    logging.info(f"Caching extraction results to MongoDB: {cache_key}")

                    # Preparing extraction metadata
                    extraction_metadata = {
                        "extracted_at": datetime.now(UTC).isoformat(),
                        DecryptionResultKeys.DECRYPTION_METHOD: DecryptionMethod.HYBRID,  # Using HybridDecryptionManager
                        "decryption_stats": stats,
                    }

                    # Saving to MongoDB cache
                    await cache_repo.set_cached_extraction(cache_key=cache_key, chat_name=room_name, room_id=room_id, start_date=start_date_str, end_date=end_date_str, messages=decrypted_messages, extraction_metadata=extraction_metadata)

                    logging.info(f"Extraction cached to MongoDB: {cache_key}")

                except Exception as e:
                    # Don't fail the extraction if caching fails
                    logging.warning(f"Failed to cache extraction to MongoDB: {e}")

            # Cleaning up decryption manager
            await decryption_manager.cleanup()

            # Closing client after extraction
            if self.client:
                await self.client.close()
                logging.info("Matrix session closed")

            return decrypted_messages_file_path

        except Exception as e:
            error_message = f"Error extracting messages from beeper: {e}"
            logger.error(error_message)
            # Closing client on error
            if self.client:
                await self.client.close()
            raise RuntimeError(error_message)

    async def extract_messages(self, messaging_platform: str, extraction_strategy_name: str, **kwargs: Any) -> str:
        """
        Extracting messages from beeper.

        LangGraph 1.0: Async method to be called from async nodes directly.
        """
        try:
            extraction_func = self.EXTRACTION_STRATEGIES_MAP.get(messaging_platform, {}).get(extraction_strategy_name)
            if not extraction_func:
                raise ValueError(f"No extraction function found for messaging platform: {messaging_platform} and purpose: {extraction_strategy_name}")

            # LangGraph 1.0: Calling async extraction function directly
            return await extraction_func(**kwargs)

        except Exception as e:
            error_message = f"Error extracting messages from beeper: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message)

    def _extract_whatsapp_group_chat_messages(self, **kwargs) -> list[Any]:
        """
        Backward compatibility wrapper - calling async method safely using multiprocessing.

        This method will call the new async implementation which uses persistent sessions.
        No manual key export needed!

        Using multiprocessing to completely isolate from FastAPI's uvloop, ensuring
        compatibility without event loop conflicts.
        """
        try:
            logging.info("Using new persistent session approach (no manual key export needed)")

            # Checking if we're already in an async context (like FastAPI)
            try:
                loop = asyncio.get_running_loop()
                # Checking if the loop is closed (can happen after asyncio.run() in parent)
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
                # We're in an async context (FastAPI with uvloop)
                logging.info("Detected running event loop - using multiprocessing for complete isolation")

                # Using multiprocessing to run async code in completely separate process
                # This avoids all uvloop/nest_asyncio compatibility issues
                import multiprocessing

                # Using Pool with context manager for clean resource handling
                ctx = multiprocessing.get_context("spawn")  # spawn ensuring clean process state
                with ctx.Pool(processes=1) as pool:
                    # Running extraction in separate process
                    async_result = pool.apply_async(_run_async_extraction_in_process, args=(self.source_name, kwargs))

                    # Waiting for result with timeout from config
                    beeper_settings = get_settings().beeper
                    result_dict = async_result.get(timeout=beeper_settings.process_timeout_seconds)

                if result_dict["success"]:
                    result_path = result_dict["result"]
                    logging.info("Successfully extracted messages using multiprocessing")
                    return result_path
                else:
                    error_msg = result_dict["error"]
                    traceback_str = result_dict.get("traceback", "")
                    logging.error(f"Beeper extraction failed in subprocess:\n{traceback_str}")
                    raise RuntimeError(f"Beeper extraction failed: {error_msg}")

            except RuntimeError as e:
                # No running loop or closed loop - we can use asyncio.run() safely
                if any(phrase in str(e).lower() for phrase in ["no running event loop", "cannot be called", "event loop is closed"]):
                    logging.info("No running event loop or loop is closed - using asyncio.run() directly")
                    result = asyncio.run(self._extract_whatsapp_group_chat_messages_async(**kwargs))
                    return result
                else:
                    # Re-raise other RuntimeErrors
                    raise

        except Exception as e:
            error_message = f"Error extracting messages from beeper: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message)

    async def _seed_mongodb_from_file_cache(self) -> None:
        """Seeding MongoDB room_id_cache from the file cache if MongoDB is empty."""
        try:
            if self._database is None or not self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH:
                return

            if not os.path.exists(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH):
                return

            if not self._room_id_cache_repo:
                from db.repositories.room_id_cache import RoomIdCacheRepository

                self._room_id_cache_repo = RoomIdCacheRepository(self._database)

            count = await self._room_id_cache_repo.count()
            if count > 0:
                logger.debug(f"MongoDB room_id_cache already has {count} entries, skipping seed")
                return

            with open(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH) as f:
                file_cache = json.load(f)

            if not file_cache:
                return

            for chat_name, room_id in file_cache.items():
                await self._room_id_cache_repo.upsert_room_mapping(chat_name, room_id)

            logger.info(f"Seeded MongoDB room_id_cache with {len(file_cache)} entries from file cache")

        except Exception as e:
            logger.warning(f"Failed to seed MongoDB from file cache: {e}")

    async def _get_room_id_with_cache(self, room_name: str) -> str:
        """
        Getting room ID with MongoDB cache (primary) and file cache (fallback).

        Args:
            room_name: Chat name to lookup

        Returns:
            Matrix room ID

        Raises:
            RuntimeError: If room ID not found
        """
        try:
            room_id = None
            settings = get_settings()

            # One-time: seed MongoDB from file cache if MongoDB is empty
            if not self._mongodb_seeded_from_file:
                self._mongodb_seeded_from_file = True
                await self._seed_mongodb_from_file_cache()

            # Step 1: Trying MongoDB cache
            room_id = await self._get_room_id_from_mongodb(room_name)
            if room_id:
                return room_id

            # Step 2: Trying file cache (if enabled as fallback)
            if settings.database.enable_room_id_file_cache:
                room_id = self._get_room_id_from_file(room_name)
                if room_id:
                    # Persisting to MongoDB so future lookups hit Step 1
                    await self._save_room_id_to_mongodb(room_name, room_id)
                    return room_id

            # Step 3: Cache miss - searching all rooms (3-6 minutes)
            logger.warning(f"Room ID cache miss for {room_name}. " f"Searching 1903 rooms (this may take 3-6 minutes)...")
            room_id = await self._find_room_id_by_name(room_name)

            if not room_id:
                raise ValueError(f"Room ID for {room_name} not found")

            # Step 4: Caching the result in MongoDB
            await self._save_room_id_to_mongodb(room_name, room_id)

            # Always saving to file cache for durability (MongoDB can be wiped)
            self._save_room_id_to_file(room_name, room_id)

            return room_id

        except Exception as e:
            error_message = f"Error getting room ID for {room_name}: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message) from e

    async def _find_room_id_by_name(self, target_name):
        """Finding a room ID by its name"""
        logger.info(f"Looking for room with name: {target_name}")
        rooms = await self._get_rooms()
        if not rooms:
            logger.warning("No rooms found or error occurred")
            return None

        # Getting room names for each room ID
        for room_id in rooms:
            try:
                room_info = await self._get_room_info(room_id)
                room_name = room_info.get("name")

                # Checking if the room name matches our target
                if room_name and room_name.lower() == target_name.lower():
                    logger.info(f"Found room ID for {target_name}: {room_id}")
                    return room_id
            except Exception as e:
                logger.warning(f"Error getting info for room {room_id}: {e}")
                continue

        logger.warning(f"Room with name '{target_name}' not found")
        return None

    async def _get_room_id_from_mongodb(self, room_name: str) -> str | None:
        """Getting room ID from MongoDB cache."""
        try:
            if self._database is None:
                logger.debug("MongoDB not available, skipping cache lookup")
                return None

            # Lazily initializing repository
            if not self._room_id_cache_repo:
                from db.repositories.room_id_cache import RoomIdCacheRepository

                self._room_id_cache_repo = RoomIdCacheRepository(self._database)

            return await self._room_id_cache_repo.get_room_id(room_name)

        except Exception as e:
            logger.warning(f"MongoDB cache lookup failed for {room_name}: {e}")
            return None

    async def _save_room_id_to_mongodb(self, room_name: str, room_id: str) -> None:
        """Saving room ID to MongoDB cache."""
        try:
            if self._database is None:
                return

            if not self._room_id_cache_repo:
                from db.repositories.room_id_cache import RoomIdCacheRepository

                self._room_id_cache_repo = RoomIdCacheRepository(self._database)

            await self._room_id_cache_repo.upsert_room_mapping(room_name, room_id)
            logger.info(f"Saved room ID to MongoDB: {room_name} -> {room_id}")

        except Exception as e:
            logger.warning(f"Failed to save room ID to MongoDB: {e}")

    def _get_room_id_from_file(self, room_name: str) -> str | None:
        """Getting room ID from file cache (legacy fallback)."""
        try:
            if not self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH:
                return None

            if not os.path.exists(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH):
                return None

            with open(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH) as f:
                cache = json.load(f)

            room_id = cache.get(room_name)

            if room_id:
                logger.info(f"File cache hit: {room_name} -> {room_id}")

            return room_id

        except Exception as e:
            logger.warning(f"Failed to read file cache: {e}")
            return None

    def _save_room_id_to_file(self, room_name: str, room_id: str) -> None:
        """Saving room ID to file cache (legacy fallback)."""
        try:
            if not self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH:
                return

            # Ensuring directory exists
            cache_dir = os.path.dirname(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            # Loading existing cache
            cache = {}
            if os.path.exists(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH):
                try:
                    with open(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH) as f:
                        cache = json.load(f)
                except Exception as e:
                    logger.warning(f"Invalid JSON in cache file, creating new cache: {e}")

            # Updating cache
            cache[room_name] = room_id

            # Saving to file
            with open(self.CHAT_NAME_TO_ROOM_ID_CACHE_PATH, "w") as f:
                json.dump(cache, f, ensure_ascii=False)

            logger.info(f"Saved room ID to file cache: {room_name} -> {room_id}")

        except Exception as e:
            logger.warning(f"Failed to save to file cache: {e}")

    async def _get_room_info(self, room_id):
        """Getting room information including the room name"""
        url = f"{_get_base_url()}/_matrix/client/r0/rooms/{room_id}/state"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=_get_headers(), timeout=TIMEOUT_HTTP_REQUEST)
            response.raise_for_status()

            # Looking for the room name event in the state events
            for event in response.json():
                if event.get("type") == MatrixEventType.ROOM_NAME:
                    return event.get("content", {})

            return {}
        except Exception as e:
            logger.error(f"Error getting room info for {room_id}: {e}")
            return {}

    async def _get_rooms(self):
        """Getting all rooms the user has joined"""
        logger.info("Fetching joined rooms...")
        url = f"{_get_base_url()}/_matrix/client/r0/joined_rooms"
        try:
            logger.debug(f"Making GET request to {url}")
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=_get_headers(), timeout=TIMEOUT_HTTP_REQUEST)
            response.raise_for_status()
            rooms = response.json().get("joined_rooms", [])
            logger.info(f"Found {len(rooms)} joined rooms")
            return rooms
        except httpx.TimeoutException:
            logger.error("Request to get_joined_rooms timed out after 30 seconds")
            return []
        except httpx.HTTPError as e:
            logger.error(f"Error fetching joined rooms: {e}")
            return []

    def _parse_timestamp(self, ts_str, day_boundary="start"):
        """Parsing timestamp string to milliseconds epoch time.

        Args:
            ts_str: Timestamp string or milliseconds as string
            day_boundary: Either "start" for beginning of day (00:00:00) or
                         "end" for end of day (23:59:59)
        """
        if ts_str.isdigit():  # Already a timestamp in milliseconds
            return int(ts_str)
        try:
            # Trying parsing common datetime formats
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", DATE_FORMAT_ISO):
                try:
                    dt = datetime.strptime(ts_str, fmt)

                    # If it's a date-only format and we need to adjust to start/end of day
                    if fmt == DATE_FORMAT_ISO:
                        if day_boundary == DayBoundary.END:
                            # Setting to end of day (23:59:59)
                            dt = dt.replace(hour=23, minute=59, second=59)
                        else:
                            # Setting to start of day (00:00:00) - this is the default behavior
                            dt = dt.replace(hour=0, minute=0, second=0)

                    return int(dt.timestamp() * 1000)  # Converting to milliseconds
                except ValueError:
                    continue
            raise ValueError(f"Could not parse timestamp: {ts_str}")
        except Exception as e:
            raise ValueError(f"Error parsing timestamp '{ts_str}': {e}")

    def _load_messages(self, message_source):
        """Loading messages from a file path or using a provided list."""
        if isinstance(message_source, str) and os.path.exists(message_source):
            with open(message_source) as f:
                return json.load(f)
        elif isinstance(message_source, list):
            return message_source
        else:
            raise ValueError("message_source must be either a valid file path or a list of messages")
