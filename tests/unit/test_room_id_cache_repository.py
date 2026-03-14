"""
Integration tests for RoomIdCacheRepository.

NOTE: These tests require a running MongoDB instance. They are integration tests
that were historically placed in unit/ but require Docker/MongoDB to run.
They are skipped automatically when MongoDB is unavailable.
"""

import pytest
from datetime import datetime

from db.connection import get_database
from db.repositories.room_id_cache import RoomIdCacheRepository


def _mongodb_available():
    """Check if MongoDB is reachable."""
    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from config import get_settings

        settings = get_settings()
        url = settings.get_mongodb_url()
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.admin.command("ping"))
            return True
        except Exception:
            return False
        finally:
            client.close()
            loop.close()
    except Exception:
        return False


requires_mongodb = pytest.mark.skipif(
    not _mongodb_available(),
    reason="MongoDB not available (Docker not running)"
)


@requires_mongodb
@pytest.mark.asyncio
async def test_upsert_room_mapping_create():
    """Test creating a new room mapping."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Test Chat"
    room_id = "!test123:beeper.local"

    result = await repo.upsert_room_mapping(chat_name, room_id)
    assert result == chat_name

    # Verify created
    cached = await repo.get_room_id(chat_name)
    assert cached == room_id


@requires_mongodb
@pytest.mark.asyncio
async def test_upsert_room_mapping_update():
    """Test updating an existing room mapping."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Test Chat"
    room_id = "!test123:beeper.local"

    # Create initial mapping
    await repo.upsert_room_mapping(chat_name, room_id)

    # Update with new room ID
    new_room_id = "!updated456:beeper.local"
    await repo.upsert_room_mapping(chat_name, new_room_id)

    # Verify updated
    cached = await repo.get_room_id(chat_name)
    assert cached == new_room_id


@requires_mongodb
@pytest.mark.asyncio
async def test_get_room_id_cache_miss():
    """Test cache miss returns None."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    result = await repo.get_room_id("Nonexistent Chat")
    assert result is None


@requires_mongodb
@pytest.mark.asyncio
async def test_access_tracking():
    """Test access count and last_accessed_at tracking."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Access Test Chat"
    room_id = "!access123:beeper.local"

    await repo.upsert_room_mapping(chat_name, room_id)

    # Access 3 times
    for _ in range(3):
        await repo.get_room_id(chat_name)

    # Verify access count
    cached = await repo.collection.find_one({"chat_name": chat_name})
    assert cached["access_count"] >= 3  # May be higher if parallel tests


@requires_mongodb
@pytest.mark.asyncio
async def test_delete_mapping():
    """Test deleting room mappings."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Delete Test Chat"
    room_id = "!delete123:beeper.local"

    # Create
    await repo.upsert_room_mapping(chat_name, room_id)
    assert await repo.get_room_id(chat_name) == room_id

    # Delete
    deleted = await repo.delete_mapping(chat_name)
    assert deleted is True

    # Verify deleted
    assert await repo.get_room_id(chat_name) is None


@requires_mongodb
@pytest.mark.asyncio
async def test_delete_nonexistent_mapping():
    """Test deleting non-existent mapping returns False."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    deleted = await repo.delete_mapping("Nonexistent Chat")
    assert deleted is False


@requires_mongodb
@pytest.mark.asyncio
async def test_get_all_mappings():
    """Test retrieving all mappings."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    # Create multiple mappings
    mappings = [
        ("Chat A", "!a123:beeper.local"),
        ("Chat B", "!b456:beeper.local"),
        ("Chat C", "!c789:beeper.local"),
    ]

    for chat_name, room_id in mappings:
        await repo.upsert_room_mapping(chat_name, room_id)

    # Get all
    all_mappings = await repo.get_all_mappings()
    assert len(all_mappings) >= 3

    # Verify sorted by chat_name
    chat_names = [m["chat_name"] for m in all_mappings]
    filtered_chat_names = [name for name in chat_names if name.startswith("Chat ")]
    assert filtered_chat_names == sorted(filtered_chat_names)


@requires_mongodb
@pytest.mark.asyncio
async def test_cache_stats():
    """Test cache statistics."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    # Create mappings
    await repo.upsert_room_mapping("Stats Chat 1", "!stats1:beeper.local")
    await repo.upsert_room_mapping("Stats Chat 2", "!stats2:beeper.local")

    # Access one of them to increase access count
    await repo.get_room_id("Stats Chat 1")
    await repo.get_room_id("Stats Chat 1")

    # Get stats
    stats = await repo.get_cache_stats()

    assert "total_entries" in stats
    assert stats["total_entries"] >= 2
    assert "top_accessed" in stats
    assert isinstance(stats["top_accessed"], list)


@requires_mongodb
@pytest.mark.asyncio
async def test_normalized_name_generation():
    """Test normalized name generation for fuzzy matching."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    # Create mapping with special characters
    chat_name = "MCP Israel #2"
    room_id = "!mcp123:beeper.local"

    await repo.upsert_room_mapping(chat_name, room_id)

    # Verify normalized_name was created
    cached = await repo.collection.find_one({"chat_name": chat_name})
    assert "normalized_name" in cached
    # Should be lowercase with underscores: "mcp_israel_2"
    assert cached["normalized_name"] == "mcp_israel_2"


@requires_mongodb
@pytest.mark.asyncio
async def test_case_sensitive_lookup():
    """Test that lookup is case-sensitive."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Test Chat"
    room_id = "!test123:beeper.local"

    await repo.upsert_room_mapping(chat_name, room_id)

    # Exact match should work
    assert await repo.get_room_id("Test Chat") == room_id

    # Different case should NOT work (cache is case-sensitive)
    assert await repo.get_room_id("test chat") is None
    assert await repo.get_room_id("TEST CHAT") is None


@requires_mongodb
@pytest.mark.asyncio
async def test_multiple_different_chats():
    """Test storing multiple different chat mappings."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    # Create multiple mappings
    mappings = {
        "LangTalks Community": "!langtalks:beeper.local",
        "MCP Israel": "!mcp_israel:beeper.local",
        "AI Transformation Guild": "!ai_guild:beeper.local",
    }

    for chat_name, room_id in mappings.items():
        await repo.upsert_room_mapping(chat_name, room_id)

    # Verify all can be retrieved
    for chat_name, expected_room_id in mappings.items():
        actual_room_id = await repo.get_room_id(chat_name)
        assert actual_room_id == expected_room_id


@requires_mongodb
@pytest.mark.asyncio
async def test_timestamp_fields():
    """Test that created_at and updated_at are set correctly."""
    db = await get_database()
    repo = RoomIdCacheRepository(db)

    chat_name = "Timestamp Test"
    room_id = "!timestamp123:beeper.local"

    # Create mapping
    await repo.upsert_room_mapping(chat_name, room_id)

    cached = await repo.collection.find_one({"chat_name": chat_name})

    # Check timestamp fields exist
    assert "created_at" in cached
    assert "updated_at" in cached
    assert "last_accessed_at" in cached

    # Check they are datetime objects
    assert isinstance(cached["created_at"], datetime)
    assert isinstance(cached["updated_at"], datetime)
    assert isinstance(cached["last_accessed_at"], datetime)
