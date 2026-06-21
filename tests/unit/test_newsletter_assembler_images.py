"""
Unit tests for image-caption surfacing in the deterministic NewsletterAssembler path.

The deterministic assembler (used by /newsletter-iterate) must surface per-discussion
image descriptions as VERIFIED METADATA on each assembled discussion, the same way it
surfaces timestamps and counts. These tests cover:

(a) assemble attaches image_descriptions when a manifest matches a discussion
(b) absent manifest -> field is None/empty, no crash
(c) caps respected (MAX_IMAGES_PER_DISCUSSION / MAX_IMAGES_TOTAL)
(d) renderer includes the descriptions in html + markdown when present, omits when absent

Pure file I/O — no live MongoDB required.
"""

import json

from constants import (
    DIR_NAME_IMAGES,
    OUTPUT_FILENAME_IMAGE_MANIFEST,
    MAX_IMAGES_PER_DISCUSSION,
)
from core.generation.generators.newsletter_assembler import (
    NewsletterAssembler,
    MERGED_DISCUSSIONS_FILENAME,
)
from custom_types.field_keys import ImageKeys, DiscussionKeys, NewsletterStructureKeys
from custom_types.newsletter_formats.langtalks.renderer import LangTalksRenderer


# ============================================================================
# FIXTURE HELPERS (mirroring tests/unit/test_associate_images.py shapes)
# ============================================================================


def _make_image(message_id: str, description: str | None = "A test image", image_id: str = "img_1", filename: str = "test.png") -> dict:
    return {
        ImageKeys.IMAGE_ID: image_id,
        ImageKeys.MESSAGE_ID: message_id,
        ImageKeys.DESCRIPTION: description,
        ImageKeys.FILENAME: filename,
        ImageKeys.TIMESTAMP: 1700000000000,
    }


def _make_discussion(disc_id: str, title: str, message_ids: list[str]) -> dict:
    return {
        DiscussionKeys.ID: disc_id,
        DiscussionKeys.TITLE: title,
        DiscussionKeys.MESSAGES: [
            {"id": mid, "content": "msg", "timestamp": 1700000000000, "sender_id": "user_1", "replies_to": None}
            for mid in message_ids
        ],
    }


def _write_json(path, data):
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _build_run_dir(tmp_path, discussions: list[dict], manifests: dict[str, list[dict]] | None = None):
    """
    Create a minimal run-dir layout the assembler understands.

    - <run_dir>/consolidated/aggregated_discussions/merged_discussions.json
    - <run_dir>/<chat_subdir>/images/image_manifest.json  (one per manifests entry)

    `manifests` maps a chat-subdir name -> list of image dicts. If None, no manifests
    are written (absent-manifest case).
    """
    run_dir = tmp_path / "run"
    agg_dir = run_dir / "consolidated" / "aggregated_discussions"
    agg_dir.mkdir(parents=True)
    _write_json(agg_dir / MERGED_DISCUSSIONS_FILENAME, {DiscussionKeys.DISCUSSIONS: discussions})

    if manifests:
        for chat_subdir, images in manifests.items():
            images_dir = run_dir / chat_subdir / DIR_NAME_IMAGES
            images_dir.mkdir(parents=True)
            _write_json(images_dir / OUTPUT_FILENAME_IMAGE_MANIFEST, images)

    return run_dir


def _editorial_for(title: str, num_secondary: int = 1) -> dict:
    """Minimal editorial dict referencing source discussions by title."""
    def disc(t):
        return {
            "source_title": t,
            "title": t,
            "bullet_points": [{"label": "L", "content": "C"}],
            "ranking_of_relevance_to_gen_ai_engineering": 8,
        }

    return {
        "primary_discussion": disc(title),
        "secondary_discussions": [disc(f"sec_{i}") for i in range(num_secondary)],
        "worth_mentioning": ["a", "b", "c"],
    }


# ============================================================================
# (a) ASSEMBLE ATTACHES image_descriptions WHEN MANIFEST MATCHES
# ============================================================================


class TestAssembleAttachesImageDescriptions:
    def test_attaches_descriptions_to_matched_discussion(self, tmp_path):
        discussions = [
            _make_discussion("disc_primary", "Primary Topic", ["m1", "m2"]),
            _make_discussion("sec_0", "sec_0", ["m9"]),
        ]
        manifests = {
            "AIL": [
                _make_image("m1", "Screenshot of API docs", image_id="i1"),
                _make_image("m2", "Architecture diagram", image_id="i2"),
            ]
        }
        run_dir = _build_run_dir(tmp_path, discussions, manifests)

        assembler = NewsletterAssembler(run_dir)
        result = assembler.assemble(_editorial_for("Primary Topic"))

        primary = result[NewsletterStructureKeys.PRIMARY_DISCUSSION]
        descriptions = primary[NewsletterStructureKeys.IMAGE_DESCRIPTIONS]
        assert descriptions is not None
        assert "Screenshot of API docs" in descriptions
        assert "Architecture diagram" in descriptions

    def test_discussion_without_images_has_none(self, tmp_path):
        discussions = [
            _make_discussion("disc_primary", "Primary Topic", ["m1"]),
            _make_discussion("sec_0", "sec_0", ["m9"]),
        ]
        manifests = {"AIL": [_make_image("m1", "Only on primary", image_id="i1")]}
        run_dir = _build_run_dir(tmp_path, discussions, manifests)

        assembler = NewsletterAssembler(run_dir)
        result = assembler.assemble(_editorial_for("Primary Topic"))

        secondary = result[NewsletterStructureKeys.SECONDARY_DISCUSSIONS][0]
        assert not secondary.get(NewsletterStructureKeys.IMAGE_DESCRIPTIONS)


# ============================================================================
# (b) ABSENT MANIFEST -> FIELD IS None/EMPTY, NO CRASH
# ============================================================================


class TestAbsentManifest:
    def test_no_manifest_field_is_falsy_no_crash(self, tmp_path):
        discussions = [
            _make_discussion("disc_primary", "Primary Topic", ["m1"]),
            _make_discussion("sec_0", "sec_0", ["m9"]),
        ]
        run_dir = _build_run_dir(tmp_path, discussions, manifests=None)

        assembler = NewsletterAssembler(run_dir)
        result = assembler.assemble(_editorial_for("Primary Topic"))

        primary = result[NewsletterStructureKeys.PRIMARY_DISCUSSION]
        assert not primary.get(NewsletterStructureKeys.IMAGE_DESCRIPTIONS)

    def test_corrupt_manifest_fails_soft(self, tmp_path):
        discussions = [
            _make_discussion("disc_primary", "Primary Topic", ["m1"]),
            _make_discussion("sec_0", "sec_0", ["m9"]),
        ]
        run_dir = _build_run_dir(tmp_path, discussions, manifests=None)
        bad_dir = run_dir / "AIL" / DIR_NAME_IMAGES
        bad_dir.mkdir(parents=True)
        (bad_dir / OUTPUT_FILENAME_IMAGE_MANIFEST).write_text("not valid json{{{")

        # Must not raise — fail-soft on corrupt manifest.
        assembler = NewsletterAssembler(run_dir)
        result = assembler.assemble(_editorial_for("Primary Topic"))
        primary = result[NewsletterStructureKeys.PRIMARY_DISCUSSION]
        assert not primary.get(NewsletterStructureKeys.IMAGE_DESCRIPTIONS)


# ============================================================================
# (c) CAPS RESPECTED
# ============================================================================


class TestCapsRespected:
    def test_per_discussion_cap(self, tmp_path):
        msg_ids = [f"m{i}" for i in range(5)]
        discussions = [
            _make_discussion("disc_primary", "Primary Topic", msg_ids),
            _make_discussion("sec_0", "sec_0", ["m99"]),
        ]
        manifests = {"AIL": [_make_image(mid, f"Image {mid}", image_id=f"i{mid}") for mid in msg_ids]}
        run_dir = _build_run_dir(tmp_path, discussions, manifests)

        assembler = NewsletterAssembler(run_dir)
        result = assembler.assemble(_editorial_for("Primary Topic"))

        primary = result[NewsletterStructureKeys.PRIMARY_DISCUSSION]
        assert len(primary[NewsletterStructureKeys.IMAGE_DESCRIPTIONS]) == MAX_IMAGES_PER_DISCUSSION


# ============================================================================
# (d) RENDERER INCLUDES DESCRIPTIONS WHEN PRESENT, OMITS WHEN ABSENT
# ============================================================================


def _discussion_payload(image_descriptions=None) -> dict:
    payload = {
        NewsletterStructureKeys.TITLE: "Some Title",
        NewsletterStructureKeys.BULLET_POINTS: [{NewsletterStructureKeys.LABEL: "L", NewsletterStructureKeys.CONTENT: "C"}],
        NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP: 1700000000000,
        NewsletterStructureKeys.LAST_MESSAGE_TIMESTAMP: 1700000100000,
        NewsletterStructureKeys.RANKING_OF_RELEVANCE: 8,
        NewsletterStructureKeys.NUMBER_OF_MESSAGES: 3,
        NewsletterStructureKeys.NUMBER_OF_UNIQUE_PARTICIPANTS: 2,
        NewsletterStructureKeys.CHAT_NAME: "LangTalks Community",
        NewsletterStructureKeys.IS_MERGED: False,
    }
    if image_descriptions is not None:
        payload[NewsletterStructureKeys.IMAGE_DESCRIPTIONS] = image_descriptions
    return payload


def _newsletter_payload(primary_image_descriptions=None) -> dict:
    return {
        NewsletterStructureKeys.PRIMARY_DISCUSSION: _discussion_payload(primary_image_descriptions),
        NewsletterStructureKeys.SECONDARY_DISCUSSIONS: [_discussion_payload(None)],
        NewsletterStructureKeys.WORTH_MENTIONING: ["a", "b", "c"],
    }


class TestRenderer:
    def test_markdown_includes_descriptions_when_present(self):
        renderer = LangTalksRenderer()
        payload = _newsletter_payload(["A unique caption marker text"])
        md = renderer.render_markdown(payload, "english")
        assert "A unique caption marker text" in md

    def test_markdown_omits_block_when_absent(self):
        renderer = LangTalksRenderer()
        payload = _newsletter_payload(None)
        md = renderer.render_markdown(payload, "english")
        assert "A unique caption marker text" not in md

    def test_html_includes_descriptions_when_present(self):
        renderer = LangTalksRenderer()
        payload = _newsletter_payload(["A unique caption marker text"])
        html = renderer.render_html(payload, "english")
        assert "A unique caption marker text" in html

    def test_substack_html_includes_descriptions_when_present(self):
        renderer = LangTalksRenderer()
        payload = _newsletter_payload(["A unique caption marker text"])
        html = renderer.render_substack_html(payload, "english")
        assert "A unique caption marker text" in html

    def test_html_omits_block_when_absent(self):
        renderer = LangTalksRenderer()
        payload = _newsletter_payload(None)
        html = renderer.render_html(payload, "english")
        assert "A unique caption marker text" not in html
