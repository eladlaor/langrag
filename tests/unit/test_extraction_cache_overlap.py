"""
Unit tests for overlap-aware extraction caching (Phase 2).

Tests the ExtractionCacheRepository overlap detection and the
SenderMapRepository persistence (Phase 3).
"""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from db.repositories.extraction_cache import ExtractionCacheRepository
from db.repositories.sender_map import SenderMapRepository
from custom_types.field_keys import DbFieldKeys


# ============================================================================
# ExtractionCacheRepository overlap tests
# ============================================================================


@pytest.fixture
def mock_db():
    db = MagicMock()
    collection = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def extraction_repo(mock_db):
    with patch("db.repositories.extraction_cache.get_settings") as mock_settings:
        mock_settings.return_value.database.extraction_cache_ttl_days = 30
        return ExtractionCacheRepository(mock_db)


@pytest.fixture
def sender_repo(mock_db):
    return SenderMapRepository(mock_db)


class TestNormalizeChatName:
    def test_basic_normalization(self, extraction_repo):
        assert extraction_repo._normalize_chat_name("LangTalks Community") == "langtalks_community"

    def test_special_characters(self, extraction_repo):
        assert extraction_repo._normalize_chat_name("MCP Israel #2") == "mcp_israel_2"

    def test_already_normalized(self, extraction_repo):
        assert extraction_repo._normalize_chat_name("simple_name") == "simple_name"

    def test_generate_cache_key_uses_normalized(self, extraction_repo):
        key = extraction_repo.generate_cache_key("LangTalks Community", "2026-03-19", "2026-04-04")
        assert key == "beeper_langtalks_community_2026-03-19_2026-04-04"


class TestGetOverlappingExtractions:
    @pytest.mark.asyncio
    async def test_no_overlap(self, extraction_repo):
        extraction_repo.find_many = AsyncMock(return_value=[])

        result = await extraction_repo.get_overlapping_extractions(
            "Test Chat", "2026-04-01", "2026-04-10"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_overlap_query_structure(self, extraction_repo):
        extraction_repo.find_many = AsyncMock(return_value=[])

        await extraction_repo.get_overlapping_extractions(
            "Test Chat", "2026-03-19", "2026-04-06"
        )

        extraction_repo.find_many.assert_called_once()
        call_args = extraction_repo.find_many.call_args
        query = call_args.kwargs.get("query") or call_args[0][0]

        # Overlap condition: cached.start <= requested.end AND cached.end >= requested.start
        assert query["chat_name_normalized"] == "test_chat"
        assert query["start_date"] == {"$lte": "2026-04-06"}
        assert query["end_date"] == {"$gte": "2026-03-19"}

    @pytest.mark.asyncio
    async def test_superset_detection(self, extraction_repo):
        """A cached range that fully contains the requested range is a superset."""
        cached_doc = {
            "cache_key": "beeper_test_chat_2026-03-15_2026-04-10",
            "start_date": "2026-03-15",
            "end_date": "2026-04-10",
            "messages": [{"event_id": "1"}, {"event_id": "2"}],
        }
        extraction_repo.find_many = AsyncMock(return_value=[cached_doc])

        result = await extraction_repo.get_overlapping_extractions(
            "Test Chat", "2026-03-19", "2026-04-06"
        )

        assert len(result) == 1
        # Verify it's a superset
        assert result[0]["start_date"] <= "2026-03-19"
        assert result[0]["end_date"] >= "2026-04-06"

    @pytest.mark.asyncio
    async def test_partial_overlap(self, extraction_repo):
        """A cached range that partially overlaps returns the document."""
        cached_doc = {
            "cache_key": "beeper_test_chat_2026-03-19_2026-04-04",
            "start_date": "2026-03-19",
            "end_date": "2026-04-04",
            "messages": [{"event_id": "1"}],
        }
        extraction_repo.find_many = AsyncMock(return_value=[cached_doc])

        result = await extraction_repo.get_overlapping_extractions(
            "Test Chat", "2026-03-19", "2026-04-06"
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_multiple_overlapping(self, extraction_repo):
        """Multiple overlapping cached ranges are all returned."""
        docs = [
            {"start_date": "2026-03-15", "end_date": "2026-03-25"},
            {"start_date": "2026-03-20", "end_date": "2026-04-04"},
        ]
        extraction_repo.find_many = AsyncMock(return_value=docs)

        result = await extraction_repo.get_overlapping_extractions(
            "Test Chat", "2026-03-19", "2026-04-06"
        )

        assert len(result) == 2


class TestSetCachedExtractionIncludesNormalized:
    @pytest.mark.asyncio
    async def test_stores_normalized_name(self, extraction_repo):
        extraction_repo.update_one = AsyncMock(return_value=True)

        await extraction_repo.set_cached_extraction(
            cache_key="beeper_test_2026-01-01_2026-01-10",
            chat_name="Test Chat #1",
            room_id="!room:beeper.local",
            start_date="2026-01-01",
            end_date="2026-01-10",
            messages=[],
        )

        extraction_repo.update_one.assert_called_once()
        call_args = extraction_repo.update_one.call_args
        doc = call_args[0][1]["$set"]
        assert doc["chat_name_normalized"] == "test_chat_1"


# ============================================================================
# SenderMapRepository tests
# ============================================================================


class TestSenderMapRepository:
    @pytest.mark.asyncio
    async def test_get_sender_map_not_found(self, sender_repo):
        sender_repo.find_one = AsyncMock(return_value=None)

        result = await sender_repo.get_sender_map("langtalks", "Test Chat")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_sender_map_found(self, sender_repo):
        sender_repo.find_one = AsyncMock(return_value={
            DbFieldKeys.DATA_SOURCE_NAME: "langtalks",
            DbFieldKeys.CHAT_NAME: "Test Chat",
            "sender_map": {"@alice:beeper.com": "user_1", "@bob:beeper.com": "user_2"},
        })

        result = await sender_repo.get_sender_map("langtalks", "Test Chat")
        assert result == {"@alice:beeper.com": "user_1", "@bob:beeper.com": "user_2"}

    @pytest.mark.asyncio
    async def test_get_sender_map_queries_correctly(self, sender_repo):
        sender_repo.find_one = AsyncMock(return_value=None)

        await sender_repo.get_sender_map("mcp_israel", "MCP Israel")

        sender_repo.find_one.assert_called_once_with({
            DbFieldKeys.DATA_SOURCE_NAME: "mcp_israel",
            DbFieldKeys.CHAT_NAME: "MCP Israel",
        })

    @pytest.mark.asyncio
    async def test_upsert_sender_map(self, sender_repo):
        sender_repo.update_one = AsyncMock(return_value=True)

        sender_map = {"@alice:beeper.com": "user_1"}
        result = await sender_repo.upsert_sender_map("langtalks", "Test Chat", sender_map)

        assert result is True
        sender_repo.update_one.assert_called_once()

        call_args = sender_repo.update_one.call_args
        query = call_args.kwargs.get("query") or call_args[0][0]
        update = call_args.kwargs.get("update") or call_args[0][1]

        assert query[DbFieldKeys.DATA_SOURCE_NAME] == "langtalks"
        assert query[DbFieldKeys.CHAT_NAME] == "Test Chat"
        assert update["$set"]["sender_map"] == sender_map
        assert update["$set"]["sender_count"] == 1

    @pytest.mark.asyncio
    async def test_upsert_uses_upsert_true(self, sender_repo):
        sender_repo.update_one = AsyncMock(return_value=True)

        await sender_repo.upsert_sender_map("langtalks", "Chat", {"a": "user_1"})

        call_args = sender_repo.update_one.call_args
        assert call_args.kwargs.get("upsert") is True or call_args[0][2] if len(call_args[0]) > 2 else call_args.kwargs.get("upsert") is True
