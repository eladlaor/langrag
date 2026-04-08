"""
Unit tests for TranslationCacheRepository.

Tests the per-message translation cache that enables incremental cross-run reuse.
Uses mocking to avoid MongoDB dependency.
"""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from db.repositories.translation_cache import TranslationCacheRepository, compute_content_hash
from custom_types.field_keys import DbFieldKeys


# ============================================================================
# compute_content_hash tests
# ============================================================================


def test_compute_content_hash_deterministic():
    """Same content always produces the same hash."""
    content = "Hello, world!"
    assert compute_content_hash(content) == compute_content_hash(content)


def test_compute_content_hash_different_for_different_content():
    """Different content produces different hashes."""
    assert compute_content_hash("Hello") != compute_content_hash("World")


def test_compute_content_hash_handles_unicode():
    """Unicode content is hashed correctly."""
    hebrew_text = "שלום עולם"
    h = compute_content_hash(hebrew_text)
    assert isinstance(h, str)
    assert len(h) == 64  # SHA256 hex digest length


def test_compute_content_hash_handles_empty_string():
    """Empty string produces a valid hash."""
    h = compute_content_hash("")
    assert isinstance(h, str)
    assert len(h) == 64


# ============================================================================
# TranslationCacheRepository tests
# ============================================================================


@pytest.fixture
def mock_db():
    """Create a mock AsyncIOMotorDatabase."""
    db = MagicMock()
    collection = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def repo(mock_db):
    """Create a TranslationCacheRepository with mocked dependencies."""
    with patch("db.repositories.translation_cache.get_settings") as mock_settings:
        mock_settings.return_value.database.translation_cache_ttl_days = 30
        return TranslationCacheRepository(mock_db)


@pytest.mark.asyncio
async def test_get_cached_translations_empty_input(repo):
    """Empty input returns empty dict without querying."""
    result = await repo.get_cached_translations([], "english")
    assert result == {}


@pytest.mark.asyncio
async def test_get_cached_translations_returns_hits(repo):
    """Cached translations are returned as a dict keyed by matrix_event_id."""
    mock_docs = [
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_1",
            DbFieldKeys.TRANSLATED_CONTENT: "Hello",
            DbFieldKeys.CONTENT_HASH: "abc123",
        },
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_2",
            DbFieldKeys.TRANSLATED_CONTENT: "World",
            DbFieldKeys.CONTENT_HASH: "def456",
        },
    ]

    repo.find_many = AsyncMock(return_value=mock_docs)

    result = await repo.get_cached_translations(["$event_1", "$event_2", "$event_3"], "english")

    assert len(result) == 2
    assert result["$event_1"]["translated_content"] == "Hello"
    assert result["$event_1"]["content_hash"] == "abc123"
    assert result["$event_2"]["translated_content"] == "World"
    assert "$event_3" not in result


@pytest.mark.asyncio
async def test_get_cached_translations_queries_correct_filter(repo):
    """Verify the MongoDB query uses correct filter."""
    repo.find_many = AsyncMock(return_value=[])

    await repo.get_cached_translations(["$ev1", "$ev2"], "hebrew")

    repo.find_many.assert_called_once()
    call_args = repo.find_many.call_args
    query = call_args.kwargs.get("query") or call_args[0][0]

    assert query[DbFieldKeys.MATRIX_EVENT_ID] == {"$in": ["$ev1", "$ev2"]}
    assert query[DbFieldKeys.TARGET_LANGUAGE] == "hebrew"


@pytest.mark.asyncio
async def test_store_translations_empty_input(repo):
    """Empty translations list returns 0 without writing."""
    result = await repo.store_translations([], "english", "Test Chat", "test_source")
    assert result == 0


@pytest.mark.asyncio
async def test_store_translations_builds_correct_operations(repo):
    """Verify bulk_write is called with correct upsert operations."""
    mock_bulk_result = MagicMock()
    mock_bulk_result.upserted_count = 2
    mock_bulk_result.modified_count = 0
    repo.collection.bulk_write = AsyncMock(return_value=mock_bulk_result)

    translations = [
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_1",
            DbFieldKeys.CONTENT: "original text",
            DbFieldKeys.TRANSLATED_CONTENT: "translated text",
        },
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_2",
            DbFieldKeys.CONTENT: "another original",
            DbFieldKeys.TRANSLATED_CONTENT: "another translated",
        },
    ]

    result = await repo.store_translations(translations, "english", "Test Chat", "test_source")

    assert result == 2
    repo.collection.bulk_write.assert_called_once()

    # Verify operations were passed
    call_args = repo.collection.bulk_write.call_args
    operations = call_args[0][0]
    assert len(operations) == 2


@pytest.mark.asyncio
async def test_store_translations_includes_content_hash(repo):
    """Stored translations include SHA256 content hash for edit detection."""
    mock_bulk_result = MagicMock()
    mock_bulk_result.upserted_count = 1
    mock_bulk_result.modified_count = 0
    repo.collection.bulk_write = AsyncMock(return_value=mock_bulk_result)

    original_content = "some original text"
    translations = [
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_1",
            DbFieldKeys.CONTENT: original_content,
            DbFieldKeys.TRANSLATED_CONTENT: "some translated text",
        },
    ]

    await repo.store_translations(translations, "english", "Chat", "source")

    call_args = repo.collection.bulk_write.call_args
    operations = call_args[0][0]
    update_doc = operations[0]._doc  # Access the UpdateOne document

    # The $set should contain the content_hash
    set_fields = update_doc["$set"]
    expected_hash = compute_content_hash(original_content)
    assert set_fields[DbFieldKeys.CONTENT_HASH] == expected_hash


@pytest.mark.asyncio
async def test_store_translations_sets_ttl(repo):
    """Stored translations have expires_at set based on TTL config."""
    mock_bulk_result = MagicMock()
    mock_bulk_result.upserted_count = 1
    mock_bulk_result.modified_count = 0
    repo.collection.bulk_write = AsyncMock(return_value=mock_bulk_result)

    translations = [
        {
            DbFieldKeys.MATRIX_EVENT_ID: "$event_1",
            DbFieldKeys.CONTENT: "text",
            DbFieldKeys.TRANSLATED_CONTENT: "translated",
        },
    ]

    before = datetime.now(UTC)
    await repo.store_translations(translations, "english", "Chat", "source")
    after = datetime.now(UTC)

    call_args = repo.collection.bulk_write.call_args
    operations = call_args[0][0]
    set_fields = operations[0]._doc["$set"]

    expires_at = set_fields[DbFieldKeys.EXPIRES_AT]
    # TTL is 30 days (from fixture)
    assert expires_at >= before + timedelta(days=30)
    assert expires_at <= after + timedelta(days=30)


@pytest.mark.asyncio
async def test_invalidate_chat_cache(repo):
    """Invalidate deletes entries for a specific chat."""
    repo.delete_many = AsyncMock(return_value=5)

    result = await repo.invalidate_chat_cache("Test Chat")

    assert result == 5
    repo.delete_many.assert_called_once_with({DbFieldKeys.CHAT_NAME: "Test Chat"})


@pytest.mark.asyncio
async def test_invalidate_chat_cache_with_language(repo):
    """Invalidate with language filter includes both chat and language in query."""
    repo.delete_many = AsyncMock(return_value=3)

    result = await repo.invalidate_chat_cache("Test Chat", target_language="english")

    assert result == 3
    repo.delete_many.assert_called_once_with({
        DbFieldKeys.CHAT_NAME: "Test Chat",
        DbFieldKeys.TARGET_LANGUAGE: "english",
    })


# ============================================================================
# Cache integration logic tests (testing the lookup/merge flow)
# ============================================================================


def test_content_hash_detects_edit():
    """When message content changes, hash changes — triggering re-translation."""
    original = "Hello world"
    edited = "Hello world!"

    original_hash = compute_content_hash(original)
    edited_hash = compute_content_hash(edited)

    assert original_hash != edited_hash
