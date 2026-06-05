"""
Unit tests for LocalMediaStorage read path and traversal guard.

Covers the serving-side primitive added for the extracted-images gallery:
reading bytes back from storage, and rejecting paths that escape base_dir.
"""

import pytest

from core.storage.media_storage import LocalMediaStorage, get_media_storage, MediaStorageInterface


@pytest.fixture
def storage(tmp_path):
    return LocalMediaStorage(base_dir=str(tmp_path))


async def test_store_then_read_roundtrip(storage):
    """Bytes written via store() come back identical via read()."""
    payload = b"\x89PNG\r\n\x1a\n fake image bytes"
    rel_path = "langtalks/some_chat/2026-01/img123_photo.png"

    returned_path = await storage.store("img123", payload, rel_path)
    assert returned_path == rel_path

    read_back = await storage.read(rel_path)
    assert read_back == payload


async def test_read_missing_file_raises(storage):
    """Reading a non-existent path raises (fail-fast, no silent empty bytes)."""
    with pytest.raises(FileNotFoundError):
        await storage.read("does/not/exist.png")


@pytest.mark.parametrize(
    "evil_path",
    [
        "../../../etc/passwd",
        "langtalks/../../../../etc/passwd",
        "/etc/passwd",
    ],
)
async def test_read_rejects_path_traversal(storage, evil_path):
    """Paths resolving outside base_dir are rejected before any file access."""
    with pytest.raises(ValueError):
        await storage.read(evil_path)


async def test_read_allows_nested_path_within_base(storage):
    """A legitimately nested relative path under base_dir is allowed."""
    payload = b"ok"
    rel_path = "a/b/c/d/img.png"
    await storage.store("img", payload, rel_path)
    assert await storage.read(rel_path) == payload


def test_get_media_storage_returns_interface(monkeypatch, tmp_path):
    """The factory returns a configured MediaStorageInterface implementation."""
    storage = get_media_storage()
    assert isinstance(storage, MediaStorageInterface)
    assert isinstance(storage, LocalMediaStorage)
