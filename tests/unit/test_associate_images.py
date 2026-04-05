"""
Unit tests for image-to-discussion association node and image context builder.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock

from graphs.single_chat_analyzer.associate_images import (
    associate_images_node,
    _build_image_discussion_map,
)
from custom_types.newsletter_formats.image_context import build_image_context_text
from custom_types.field_keys import ImageKeys, DiscussionKeys
from graphs.state_keys import SingleChatStateKeys as Keys


# ============================================================================
# TEST DATA HELPERS
# ============================================================================


def _make_image(message_id: str, description: str | None = "A test image", image_id: str = "img_1", filename: str = "test.png") -> dict:
    """Create a minimal image metadata dict."""
    return {
        ImageKeys.IMAGE_ID: image_id,
        ImageKeys.MESSAGE_ID: message_id,
        ImageKeys.DESCRIPTION: description,
        ImageKeys.FILENAME: filename,
        ImageKeys.TIMESTAMP: 1700000000000,
    }


def _make_discussion(disc_id: str, title: str, message_ids: list[str]) -> dict:
    """Create a minimal discussion dict with embedded messages."""
    return {
        DiscussionKeys.ID: disc_id,
        DiscussionKeys.TITLE: title,
        DiscussionKeys.MESSAGES: [{"id": mid, "content": "msg", "timestamp": 1700000000000, "sender_id": "user_1", "replies_to": None} for mid in message_ids],
    }


def _write_json(path, data):
    """Write data as JSON to path."""
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f)


# ============================================================================
# _build_image_discussion_map TESTS
# ============================================================================


class TestBuildImageDiscussionMap:
    """Tests for the core image-to-discussion matching logic."""

    def test_matches_images_to_discussions_by_message_id(self, tmp_path):
        """Images are matched to discussions via message_id."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [
            _make_image("msg_1", "Screenshot of API docs", image_id="img_1"),
            _make_image("msg_3", "Architecture diagram", image_id="img_2"),
        ])
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "API Discussion", ["msg_1", "msg_2"]),
                _make_discussion("disc_B", "Architecture", ["msg_3", "msg_4"]),
            ]
        })

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert "disc_A" in result
        assert "disc_B" in result
        assert len(result["disc_A"]) == 1
        assert result["disc_A"][0][ImageKeys.DESCRIPTION] == "Screenshot of API docs"
        assert result["disc_B"][0][ImageKeys.DESCRIPTION] == "Architecture diagram"

    def test_skips_images_without_description(self, tmp_path):
        """Images with no description are excluded from the map."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [
            _make_image("msg_1", description=None, image_id="img_1"),
            _make_image("msg_2", description="Valid description", image_id="img_2"),
        ])
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "Test", ["msg_1", "msg_2"]),
            ]
        })

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert len(result["disc_A"]) == 1
        assert result["disc_A"][0][ImageKeys.DESCRIPTION] == "Valid description"

    def test_skips_images_with_no_matching_discussion(self, tmp_path):
        """Images whose message_id doesn't match any discussion are excluded."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [_make_image("msg_orphan", "Orphan image")])
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "Test", ["msg_1"]),
            ]
        })

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert result == {}

    def test_caps_images_per_discussion(self, tmp_path):
        """Respects MAX_IMAGES_PER_DISCUSSION cap (3)."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        images = [_make_image(f"msg_{i}", f"Image {i}", image_id=f"img_{i}") for i in range(5)]
        _write_json(manifest, images)
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "Busy discussion", [f"msg_{i}" for i in range(5)]),
            ]
        })

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert len(result["disc_A"]) == 3

    def test_caps_total_images(self, tmp_path):
        """Respects MAX_IMAGES_TOTAL cap (15)."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        # 6 discussions x 3 images each = 18, should be capped to 15
        all_images = []
        all_discussions = []
        for d in range(6):
            msg_ids = [f"msg_{d}_{i}" for i in range(3)]
            all_discussions.append(_make_discussion(f"disc_{d}", f"Discussion {d}", msg_ids))
            for i, mid in enumerate(msg_ids):
                all_images.append(_make_image(mid, f"Image {d}-{i}", image_id=f"img_{d}_{i}"))

        _write_json(manifest, all_images)
        _write_json(discussions, {DiscussionKeys.DISCUSSIONS: all_discussions})

        result = _build_image_discussion_map(str(manifest), str(discussions))

        total = sum(len(imgs) for imgs in result.values())
        assert total <= 15

    def test_returns_empty_dict_when_no_images(self, tmp_path):
        """Returns empty dict when manifest has no images."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [])
        _write_json(discussions, {DiscussionKeys.DISCUSSIONS: [_make_discussion("d1", "Test", ["msg_1"])]})

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert result == {}

    def test_handles_discussions_as_plain_list(self, tmp_path):
        """Works when discussions file is a plain list (not wrapped in {discussions: ...})."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [_make_image("msg_1", "Test image")])
        _write_json(discussions, [_make_discussion("disc_A", "Test", ["msg_1"])])

        result = _build_image_discussion_map(str(manifest), str(discussions))

        assert "disc_A" in result

    def test_raises_on_corrupt_manifest(self, tmp_path):
        """ValueError raised when manifest JSON is corrupt."""
        manifest = tmp_path / "manifest.json"
        manifest.write_text("not valid json{{{")
        discussions = tmp_path / "discussions.json"
        _write_json(discussions, {DiscussionKeys.DISCUSSIONS: []})

        with pytest.raises(ValueError, match="Failed to load image manifest"):
            _build_image_discussion_map(str(manifest), str(discussions))

    def test_raises_on_corrupt_discussions(self, tmp_path):
        """ValueError raised when discussions JSON is corrupt."""
        manifest = tmp_path / "manifest.json"
        _write_json(manifest, [])
        discussions = tmp_path / "discussions.json"
        discussions.write_text("not valid json{{{")

        with pytest.raises(ValueError, match="Failed to load discussions"):
            _build_image_discussion_map(str(manifest), str(discussions))


# ============================================================================
# associate_images_node TESTS
# ============================================================================


class TestAssociateImagesNode:
    """Tests for the associate_images_node graph node."""

    @pytest.mark.asyncio
    async def test_skips_when_image_extraction_disabled(self):
        """Returns None map when enable_image_extraction is False."""
        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: False,
            Keys.IMAGE_MANIFEST_PATH: "/some/path",
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None

    @pytest.mark.asyncio
    async def test_skips_when_no_manifest_path(self):
        """Returns None map when image_manifest_path is None."""
        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: None,
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None

    @pytest.mark.asyncio
    async def test_skips_when_manifest_file_missing(self, tmp_path):
        """Returns None map when manifest file doesn't exist on disk."""
        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: str(tmp_path / "nonexistent.json"),
            Keys.SEPARATE_DISCUSSIONS_FILE_PATH: str(tmp_path / "discussions.json"),
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None

    @pytest.mark.asyncio
    async def test_skips_when_discussions_file_missing(self, tmp_path):
        """Returns None map when discussions file doesn't exist."""
        manifest = tmp_path / "manifest.json"
        _write_json(manifest, [])

        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: str(manifest),
            Keys.SEPARATE_DISCUSSIONS_FILE_PATH: str(tmp_path / "nonexistent.json"),
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None

    @pytest.mark.asyncio
    @patch("graphs.single_chat_analyzer.associate_images._update_mongodb_discussion_ids", new_callable=AsyncMock)
    async def test_returns_map_on_success(self, mock_update_mongo, tmp_path):
        """Returns populated map when images match discussions."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [_make_image("msg_1", "A screenshot", image_id="img_1")])
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "Test Discussion", ["msg_1", "msg_2"]),
            ]
        })

        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: str(manifest),
            Keys.SEPARATE_DISCUSSIONS_FILE_PATH: str(discussions),
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is not None
        assert "disc_A" in result[Keys.IMAGE_DISCUSSION_MAP]
        assert len(result[Keys.IMAGE_DISCUSSION_MAP]["disc_A"]) == 1
        mock_update_mongo.assert_called_once()

    @pytest.mark.asyncio
    @patch("graphs.single_chat_analyzer.associate_images._update_mongodb_discussion_ids", new_callable=AsyncMock)
    async def test_returns_none_when_no_matches(self, mock_update_mongo, tmp_path):
        """Returns None map when no images match any discussion."""
        manifest = tmp_path / "manifest.json"
        discussions = tmp_path / "discussions.json"

        _write_json(manifest, [_make_image("msg_orphan", "Orphan")])
        _write_json(discussions, {
            DiscussionKeys.DISCUSSIONS: [
                _make_discussion("disc_A", "Test", ["msg_1"]),
            ]
        })

        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: str(manifest),
            Keys.SEPARATE_DISCUSSIONS_FILE_PATH: str(discussions),
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None
        mock_update_mongo.assert_not_called()

    @pytest.mark.asyncio
    async def test_failsoft_on_corrupt_manifest(self, tmp_path):
        """Returns None map on corrupt manifest (fail-soft, no exception)."""
        manifest = tmp_path / "manifest.json"
        manifest.write_text("corrupt{{{")
        discussions = tmp_path / "discussions.json"
        _write_json(discussions, {DiscussionKeys.DISCUSSIONS: []})

        state = {
            Keys.ENABLE_IMAGE_EXTRACTION: True,
            Keys.IMAGE_MANIFEST_PATH: str(manifest),
            Keys.SEPARATE_DISCUSSIONS_FILE_PATH: str(discussions),
        }

        result = await associate_images_node(state)

        assert result[Keys.IMAGE_DISCUSSION_MAP] is None


# ============================================================================
# build_image_context_text TESTS
# ============================================================================


class TestBuildImageContextText:
    """Tests for the shared image context builder used by format plugins."""

    def test_returns_empty_string_when_map_is_none(self):
        """Returns empty string when image_discussion_map is None."""
        result = build_image_context_text([], None)

        assert result == ""

    def test_returns_empty_string_when_map_is_empty(self):
        """Returns empty string when image_discussion_map is empty dict."""
        result = build_image_context_text([], {})

        assert result == ""

    def test_returns_empty_string_when_no_matching_discussions(self):
        """Returns empty string when map has IDs not in discussions list."""
        discussions = [_make_discussion("disc_A", "Test", ["msg_1"])]
        image_map = {"disc_UNKNOWN": [{ImageKeys.DESCRIPTION: "A screenshot"}]}

        result = build_image_context_text(discussions, image_map)

        assert result == ""

    def test_builds_context_for_single_discussion(self):
        """Produces correct format for a single discussion with images."""
        discussions = [_make_discussion("disc_A", "API Discussion", ["msg_1"])]
        image_map = {
            "disc_A": [
                {ImageKeys.DESCRIPTION: "Screenshot of API docs"},
                {ImageKeys.DESCRIPTION: "Terminal output"},
            ]
        }

        result = build_image_context_text(discussions, image_map)

        assert "IMAGE CONTEXT:" in result
        assert 'Discussion "API Discussion"' in result
        assert "- Screenshot of API docs" in result
        assert "- Terminal output" in result

    def test_builds_context_for_multiple_discussions(self):
        """Produces sections for each discussion with images."""
        discussions = [
            _make_discussion("disc_A", "First Topic", ["msg_1"]),
            _make_discussion("disc_B", "Second Topic", ["msg_2"]),
        ]
        image_map = {
            "disc_A": [{ImageKeys.DESCRIPTION: "Image A"}],
            "disc_B": [{ImageKeys.DESCRIPTION: "Image B"}],
        }

        result = build_image_context_text(discussions, image_map)

        assert 'Discussion "First Topic"' in result
        assert 'Discussion "Second Topic"' in result
        assert "- Image A" in result
        assert "- Image B" in result

    def test_skips_images_without_description(self):
        """Skips image entries that have no description."""
        discussions = [_make_discussion("disc_A", "Test", ["msg_1"])]
        image_map = {
            "disc_A": [
                {ImageKeys.DESCRIPTION: None},
                {ImageKeys.DESCRIPTION: "Valid"},
            ]
        }

        result = build_image_context_text(discussions, image_map)

        assert "- Valid" in result
        assert result.count("- ") == 1
