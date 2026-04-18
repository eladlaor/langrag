"""
Media Storage Interface and Local Implementation

Provides an abstraction for persistent image/media storage.
Local filesystem implementation uses an S3-like path structure
for easy future migration to MinIO/S3.

Storage path convention:
    data/media/images/{data_source_name}/{chat_slug}/{YYYY-MM}/{image_id}_{filename}
"""

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, UTC

import aiofiles

from constants import MS_TO_SECONDS_MULTIPLIER

logger = logging.getLogger(__name__)

# Timestamps above this value are in milliseconds (epoch ms for year ~2001+)
_MS_TIMESTAMP_THRESHOLD = 1_000_000_000_000


class MediaStorageInterface(ABC):
    """Abstract interface for persistent media storage."""

    @abstractmethod
    async def store(self, image_id: str, data: bytes, path: str) -> str:
        """Store image data at the given path. Returns the storage path."""
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        ...

    @abstractmethod
    def get_persistent_path(
        self,
        data_source_name: str,
        chat_name: str,
        timestamp_ms: int,
        image_id: str,
        filename: str,
    ) -> str:
        """Build the canonical storage path for an image."""
        ...


class LocalMediaStorage(MediaStorageInterface):
    """Local filesystem storage with S3-like path structure."""

    def __init__(self, base_dir: str):
        self._base_dir = base_dir

    async def store(self, image_id: str, data: bytes, path: str) -> str:
        full_path = os.path.join(self._base_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(data)
        return path

    async def exists(self, path: str) -> bool:
        full_path = os.path.join(self._base_dir, path)
        return await asyncio.to_thread(os.path.exists, full_path)

    def get_persistent_path(
        self,
        data_source_name: str,
        chat_name: str,
        timestamp_ms: int,
        image_id: str,
        filename: str,
    ) -> str:
        chat_slug = _slugify(chat_name)
        ts_seconds = timestamp_ms / MS_TO_SECONDS_MULTIPLIER if timestamp_ms > _MS_TIMESTAMP_THRESHOLD else timestamp_ms
        month_str = datetime.fromtimestamp(ts_seconds, tz=UTC).strftime("%Y-%m")
        safe_filename = _safe_filename(filename) or "image"
        return os.path.join(data_source_name, chat_slug, month_str, f"{image_id}_{safe_filename}")

    def get_full_path(self, relative_path: str) -> str:
        return os.path.join(self._base_dir, relative_path)


def _slugify(text: str) -> str:
    """Convert text to filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "_", slug)
    return slug


def _safe_filename(filename: str) -> str:
    """Remove unsafe characters from filename."""
    if not filename:
        return ""
    safe = re.sub(r"[^\w.\-]", "_", filename)
    return safe[:100]
