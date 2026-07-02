"""
TDD (failing-first) tests for the FINAL NEWSLETTER TRIPLET.

Spec: knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md (Part A, A1).

Target behavior locked here:
  * After the consolidated translate node runs, the FINAL stage dir holds a
    full triplet: final_newsletter.{md,html,json}, all non-empty.
  * The final html carries every enriched content link (count matches the
    enriched json, and exceeds the pre-enrichment draft).
  * With target language != generation language, final md/html render in the
    target language.

These MUST fail against current code: the translate node only writes
`translated_consolidated.md`, renders no html/json, and returns no
CONSOLIDATED_FINAL_* state keys.

Design note: the translate node reaches the LLM via
ContentGeneratorFactory.create(...).generate_content(...). We patch that
factory with a deterministic fake that performs the *structured* translate the
A1 design mandates (translate text fields, preserve keys/URLs), so the test is
deterministic and network-free. The fake also emulates the legacy md-only
write so that, if the node still runs the old path, it does not crash for an
unrelated reason (the test then fails on the missing triplet, which is the
point).
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from constants import SummaryFormats
from custom_types.field_keys import NewsletterStructureKeys as NSK
from custom_types.newsletter_formats import get_format
from graphs.state_keys import OrchestratorKeys
from graphs.multi_chat_consolidator import consolidation_nodes

from ._final_triplet_helpers import (
    ENRICHED_CONTENT_URLS,
    content_hrefs,
    content_md_links,
    make_draft_newsletter_dict,
    make_enriched_newsletter_dict,
    write_enriched_stage,
)

FACTORY_PATH = "core.generation.generators.factory.ContentGeneratorFactory"

# A trivial "translation": prefix a target-language token onto every text
# field, leaving keys and URLs untouched. Distinct enough to detect language.
TARGET_LANG_TOKEN = "[EN]"


def _translate_text(text: str) -> str:
    return f"{TARGET_LANG_TOKEN} {text}"


def _translate_structured(newsletter_dict: dict) -> dict:
    """Deterministic structured translate: text fields prefixed, URLs intact."""
    out = json.loads(json.dumps(newsletter_dict))  # deep copy

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in (NSK.TITLE, NSK.LABEL, NSK.CONTENT) and isinstance(v, str):
                    node[k] = _translate_text(v)
                else:
                    _walk(v)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, str):
                    node[i] = _translate_text(item)
                else:
                    _walk(item)

    _walk(out)
    return out


class _FakeContentGenerator:
    """Emulates both the target structured-translate op and the legacy md write."""

    def __init__(self, enriched_dict: dict, summary_format: str):
        self._enriched = enriched_dict
        self._fmt = get_format(summary_format)

    async def generate_content(self, operation, **kwargs):
        translated = _translate_structured(self._enriched)

        # Emulate the target A1 structured-translate contract: return the
        # translated dict so the node can render the triplet from it.
        # Also honor the legacy contract (write md at expected path) so the old
        # code path does not error for an unrelated reason.
        expected = kwargs.get("expected_final_translated_file_path")
        if expected:
            os.makedirs(os.path.dirname(expected), exist_ok=True)
            with open(expected, "w", encoding="utf-8") as f:
                f.write(self._fmt.render_markdown(translated, "english"))

        return {
            "summary": self._fmt.render_markdown(translated, "english"),
            "translated_newsletter": translated,
        }


def _base_state(tmp_path, enriched_json, enriched_md, translation_dir, expected_translated, language="english"):
    return {
        OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY: language,
        OrchestratorKeys.EXPECTED_CONSOLIDATED_TRANSLATED_FILE: expected_translated,
        OrchestratorKeys.FORCE_REFRESH_CONSOLIDATED_TRANSLATION: True,
        OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH: enriched_md,
        OrchestratorKeys.CONSOLIDATED_ENRICHED_JSON_PATH: enriched_json,
        OrchestratorKeys.CONSOLIDATED_TRANSLATION_DIR: translation_dir,
        OrchestratorKeys.DATA_SOURCE_NAME: "langtalks",
        OrchestratorKeys.SUMMARY_FORMAT: str(SummaryFormats.LANGTALKS_FORMAT),
        OrchestratorKeys.START_DATE: "2026-06-01",
        OrchestratorKeys.END_DATE: "2026-07-01",
        OrchestratorKeys.CHAT_NAMES: ["LangTalks Community"],
        # No MONGODB_RUN_ID -> node skips persistence entirely.
    }


async def _run_translate_node(tmp_path, language="hebrew"):
    """Drive the real translate node with a fake generator; return (result, dirs).

    Uses a non-English target by default so translation actually runs (the node
    short-circuits for English targets).
    """
    consolidated = tmp_path / "consolidated"
    enrichment_dir = str(consolidated / "link_enrichment")
    translation_dir = str(consolidated / "final")
    os.makedirs(translation_dir, exist_ok=True)

    enriched_dict = make_enriched_newsletter_dict()
    enriched_json, enriched_md = write_enriched_stage(enrichment_dir, enriched_dict)

    expected_translated = os.path.join(translation_dir, "translated_consolidated.md")
    state = _base_state(tmp_path, enriched_json, enriched_md, translation_dir, expected_translated, language)

    fake = _FakeContentGenerator(enriched_dict, str(SummaryFormats.LANGTALKS_FORMAT))
    with patch(f"{FACTORY_PATH}.create", return_value=fake):
        result = await consolidation_nodes.translate_consolidated_newsletter(state, None)

    return result, translation_dir


def _final_paths_from_result(result, translation_dir):
    """Resolve the final triplet paths from the node's returned state.

    Prefers the target CONSOLIDATED_FINAL_* keys. Falls back to scanning the
    final dir for a final_newsletter.* triplet if the keys are absent, so the
    assertion pinpoints the real gap (missing artifacts vs missing keys).
    """
    keys = {}
    for attr in ("CONSOLIDATED_FINAL_JSON_PATH", "CONSOLIDATED_FINAL_MD_PATH", "CONSOLIDATED_FINAL_HTML_PATH"):
        key = getattr(OrchestratorKeys, attr, None)
        if key is not None:
            keys[attr] = result.get(key)
    return keys


@pytest.mark.asyncio
async def test_final_triplet_written(tmp_path):
    """final_newsletter.{md,html,json} all exist and are non-empty after translate."""
    result, translation_dir = await _run_translate_node(tmp_path, language="hebrew")

    # Target: the final dir holds a complete triplet.
    md = os.path.join(translation_dir, "final_newsletter.md")
    html = os.path.join(translation_dir, "final_newsletter.html")
    js = os.path.join(translation_dir, "final_newsletter.json")

    for p in (md, html, js):
        assert os.path.exists(p), f"final triplet member missing: {p}"
        assert os.path.getsize(p) > 0, f"final triplet member empty: {p}"

    # json must be valid, structured (not an empty stub).
    with open(js, encoding="utf-8") as f:
        data = json.load(f)
    assert data.get(NSK.PRIMARY_DISCUSSION), "final json missing primary_discussion"


@pytest.mark.asyncio
async def test_final_html_has_enriched_links(tmp_path):
    """Final html carries every enriched content link; count > draft's links."""
    _result, translation_dir = await _run_translate_node(tmp_path, language="hebrew")

    html_path = os.path.join(translation_dir, "final_newsletter.html")
    json_path = os.path.join(translation_dir, "final_newsletter.json")
    assert os.path.exists(html_path), "final html not rendered"

    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    with open(json_path, encoding="utf-8") as f:
        final_dict = json.load(f)

    html_urls = set(content_hrefs(html))

    # Every enriched content URL survives into the delivered html.
    for url in ENRICHED_CONTENT_URLS:
        assert url in html_urls, f"enriched link dropped from final html: {url}"

    # Link count in html matches the enriched/final json's clickable links.
    fmt = get_format(str(SummaryFormats.LANGTALKS_FORMAT))
    json_md_urls = set(content_md_links(fmt.render_markdown(final_dict, "english")))
    assert html_urls == json_md_urls, "final html link set != final json link set"

    # And it strictly exceeds the pre-enrichment draft (the 6-vs-2 defect).
    draft = make_draft_newsletter_dict()
    draft_html = fmt.render_html(draft, "english")
    assert len(html_urls) > len(set(content_hrefs(draft_html))), "final html did not add enrichment links over the draft"


@pytest.mark.asyncio
async def test_final_is_target_language(tmp_path):
    """With target != generation language, final md/html are in the target language."""
    _result, translation_dir = await _run_translate_node(tmp_path, language="hebrew")

    md_path = os.path.join(translation_dir, "final_newsletter.md")
    html_path = os.path.join(translation_dir, "final_newsletter.html")
    assert os.path.exists(md_path) and os.path.exists(html_path), "final md/html not rendered"

    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    # The deterministic fake tags every translated text field. If the final
    # output was rendered from the TRANSLATED dict, the token appears; if it was
    # rendered from the untranslated draft/enriched dict, it does not.
    assert TARGET_LANG_TOKEN in md, "final md not rendered from translated content"
    assert TARGET_LANG_TOKEN in html, "final html not rendered from translated content"
