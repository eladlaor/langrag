"""
Unit tests for the extracted-images gallery endpoint helpers and the
ImagesRepository composable-query construction.

These cover the new logic without requiring a live MongoDB: the response
projection, the serving-URL builder, the discussion-title batch resolution,
and the filter -> Mongo-query mapping in query_images/count_images.
"""

from unittest.mock import AsyncMock

from api.images import _image_serving_url, _to_item, _resolve_discussion_titles
from constants import API_V1_PREFIX, COLLECTION_IMAGES
from custom_types.field_keys import DbFieldKeys, ImageKeys
from db.repositories.images import ImagesRepository


# ============================================================================
# Endpoint helpers
# ============================================================================


def test_image_serving_url_points_at_media_route():
    url = _image_serving_url("abc123")
    assert url == f"{API_V1_PREFIX}/media/images/abc123"


def test_to_item_projects_all_fields_and_resolves_title():
    image = {
        "_id": "img1",
        ImageKeys.CHAT_NAME: "MCP Israel",
        ImageKeys.DATA_SOURCE_NAME: "mcp_israel",
        ImageKeys.TIMESTAMP: 1700000000000,
        ImageKeys.SENDER_ID: "user_7",
        ImageKeys.MIMETYPE: "image/png",
        ImageKeys.WIDTH: 800,
        ImageKeys.HEIGHT: 600,
        ImageKeys.SIZE_BYTES: 12345,
        ImageKeys.FILENAME: "diagram.png",
        ImageKeys.DESCRIPTION: "An architecture diagram",
        ImageKeys.DISCUSSION_ID: "disc1",
    }
    item = _to_item(image, {"disc1": "RAG architecture"})

    assert item.image_id == "img1"
    assert item.image_url == f"{API_V1_PREFIX}/media/images/img1"
    assert item.chat_name == "MCP Israel"
    assert item.data_source_name == "mcp_israel"
    assert item.timestamp == 1700000000000
    assert item.mimetype == "image/png"
    assert item.discussion_id == "disc1"
    assert item.discussion_title == "RAG architecture"


def test_to_item_handles_missing_discussion():
    image = {"_id": "img2"}
    item = _to_item(image, {})
    assert item.discussion_id is None
    assert item.discussion_title is None
    assert item.image_url.endswith("/media/images/img2")


async def test_resolve_discussion_titles_empty_set_skips_query():
    repo = AsyncMock()
    result = await _resolve_discussion_titles(repo, set())
    assert result == {}
    repo.find_many.assert_not_called()


async def test_resolve_discussion_titles_maps_id_to_title():
    repo = AsyncMock()
    repo.find_many.return_value = [
        {DbFieldKeys.DISCUSSION_ID: "d1", DbFieldKeys.TITLE: "First"},
        {DbFieldKeys.DISCUSSION_ID: "d2", DbFieldKeys.TITLE: "Second"},
    ]
    result = await _resolve_discussion_titles(repo, {"d1", "d2"})
    assert result == {"d1": "First", "d2": "Second"}


# ============================================================================
# Repository composable query construction
# ============================================================================


def _repo_with_mocked_collection() -> ImagesRepository:
    """Build an ImagesRepository whose Mongo collection is a mock."""
    fake_db = {COLLECTION_IMAGES: AsyncMock()}
    repo = ImagesRepository(fake_db)
    return repo


async def test_query_images_builds_anded_filter():
    repo = _repo_with_mocked_collection()
    repo.find_many = AsyncMock(return_value=[])

    await repo.query_images(
        data_source_name="langtalks",
        chat_name="LangTalks Community",
        discussion_id="disc9",
        start_date="2026-01-01",
        end_date="2026-01-31",
        limit=10,
        offset=20,
    )

    query, kwargs = repo.find_many.call_args.args[0], repo.find_many.call_args.kwargs
    assert query[ImageKeys.DATA_SOURCE_NAME] == "langtalks"
    assert query[ImageKeys.CHAT_NAME] == "LangTalks Community"
    assert query[ImageKeys.DISCUSSION_ID] == "disc9"
    assert "$gte" in query[ImageKeys.TIMESTAMP]
    assert "$lte" in query[ImageKeys.TIMESTAMP]
    assert kwargs["limit"] == 10
    assert kwargs["skip"] == 20
    # Newest-first ordering
    assert kwargs["sort"] == [(ImageKeys.TIMESTAMP, -1)]


async def test_query_images_omits_absent_filters():
    repo = _repo_with_mocked_collection()
    repo.find_many = AsyncMock(return_value=[])

    await repo.query_images()

    query = repo.find_many.call_args.args[0]
    assert query == {}


async def test_count_images_uses_same_filters_without_pagination():
    repo = _repo_with_mocked_collection()
    repo.count = AsyncMock(return_value=3)

    total = await repo.count_images(data_source_name="mcp_israel", discussion_id="d5")

    assert total == 3
    query = repo.count.call_args.args[0]
    assert query[ImageKeys.DATA_SOURCE_NAME] == "mcp_israel"
    assert query[ImageKeys.DISCUSSION_ID] == "d5"
