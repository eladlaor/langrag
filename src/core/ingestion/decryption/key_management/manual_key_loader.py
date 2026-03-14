"""Manual key loader for decrypted Megolm keys.

This module handles loading of manually decrypted Megolm keys from JSON files.
Extracted from beeper.py to follow DRY principle and separation of concerns.
"""

import json
import logging
from pathlib import Path
from typing import Any

from core.ingestion.decryption.exceptions import KeyManagementError

logger = logging.getLogger(__name__)


class ManualKeyLoader:
    """
    Load manually decrypted Megolm keys from JSON files.

    Handles path resolution for keys files that may be specified as
    absolute or relative paths.
    """

    def load_keys(self, keys_file_path: str) -> list[dict[str, Any]]:
        """
        Load decryption keys from a JSON file.

        Tries multiple path resolution strategies:
        1. Absolute path as-is
        2. Relative to current working directory
        3. Relative to project root

        Args:
            keys_file_path: Path to the decrypted keys JSON file

        Returns:
            List of decryption key dictionaries

        Raises:
            KeyManagementError: If file cannot be found or loaded
        """
        try:
            resolved_path = self._resolve_path(keys_file_path)

            with open(resolved_path) as f:
                keys = json.load(f)

            logger.info(f"Loaded {len(keys)} decryption keys from {resolved_path}")
            return keys

        except FileNotFoundError:
            raise KeyManagementError(f"Decryption keys file not found: {keys_file_path}. " f"Tried: current dir, project root")
        except json.JSONDecodeError as e:
            raise KeyManagementError(f"Invalid JSON in keys file {keys_file_path}: {e}")
        except Exception as e:
            raise KeyManagementError(f"Failed to load keys from {keys_file_path}: {e}")

    def _resolve_path(self, keys_file_path: str) -> Path:
        """
        Resolve keys file path using multiple strategies.

        Args:
            keys_file_path: Path to resolve (absolute or relative)

        Returns:
            Resolved absolute Path object

        Raises:
            FileNotFoundError: If file cannot be found in any location
        """
        path = Path(keys_file_path)

        # Strategy 1: Already absolute and exists
        if path.is_absolute() and path.exists():
            return path

        # Strategy 2: Relative to current working directory
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path

        # Strategy 3: Relative to project root (assume we're in src/)
        # Go up from src/core/ingestion/decryption/key_management to project root
        project_root = Path(__file__).parents[5]  # Go up 5 levels
        root_path = project_root / path
        if root_path.exists():
            return root_path

        # None of the strategies worked
        raise FileNotFoundError(f"Could not resolve path: {keys_file_path}")
