"""TDD (failing-first) tests for the CONSOLIDATED final-triplet fixes.

Spec: knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md (Part A) plus the
review findings on the final-triplet refactor.

Target behavior locked here:
  1. A consolidated run with target language ENGLISH still writes the full
     final_newsletter.{md,html,json} triplet and sets CONSOLIDATED_FINAL_HTML_PATH
     (the English early-return bug drops the triplet today).
  2. With a consolidated final html present AND per-chat final htmls present,
     _find_best_html_path returns the CONSOLIDATED final html, not a per-chat one.
  3. For a NON-English run, final_newsletter.json retains the enrichment-only
     top-level keys present in the enriched dict (parity with English), which the
     strict-schema structured translate would otherwise drop.

Tests 1 and 3 MUST fail against current code (English early-return; strict-schema
drop of enrichment-only keys). Test 2 is a guard the resolver must satisfy.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from constants import SummaryFormats
from custom_types.field_keys import NewsletterStructureKeys as NSK
from custom_types.newsletter_formats import get_format
from graphs.state_keys import OrchestratorKeys, SingleChatKeys
from graphs.multi_chat_consolidator import consolidation_nodes
from graphs.multi_chat_consolidator import graph as consolidator_graph

from ._final_triplet_helpers import (
    content_hrefs,
    make_enriched_newsletter_dict,
    write_enriched_stage,
)

FACTORY_PATH = "core.generation.generators.factory.ContentGeneratorFactory"

TARGET_LANG_TOKEN = "[XLATE]"

# Enrichment-only top-level keys the enriched dict carries but the strict
# generation schema does NOT, so a schema-pinned structured translate drops them.
ENRICHMENT_ONLY_KEYS = {
    NSK.LINK_ENRICHMENT_METADATA: {"provider": "tavily", "queries": 4},
    NSK.LINKS_INSERTED: 6,
    NSK.METADATA: {"generated_at": "2026-07-01T00:00:00Z"},
}


def _translate_structured(newsletter_dict: dict) -> dict:
    """Deterministic structured translate honoring the strict generation schema.

    Mirrors the real strict-schema behavior: it returns ONLY the generation-shape
    keys (primary/secondary/worth_mentioning), translating text fields and
    preserving URLs, and DROPS enrichment-only top-level keys. This is what makes
    the metadata-parity test fail until the node merges those keys back.
    """
    schema_keys = {NSK.PRIMARY_DISCUSSION, NSK.SECONDARY_DISCUSSIONS, NSK.WORTH_MENTIONING}
    pruned = {k: v for k, v in newsletter_dict.items() if k in schema_keys}
    out = json.loads(json.dumps(pruned))  # deep copy

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in (NSK.TITLE, NSK.LABEL, NSK.CONTENT) and isinstance(v, str):
                    node[k] = f"{TARGET_LANG_TOKEN} {v}"
                else:
                    _walk(v)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, str):
                    node[i] = f"{TARGET_LANG_TOKEN} {item}"
                else:
                    _walk(item)

    _walk(out)
    return out


class _FakeContentGenerator:
    def __init__(self, enriched_dict: dict, summary_format: str):
        self._enriched = enriched_dict
        self._fmt = get_format(summary_format)

    async def generate_content(self, operation, **kwargs):
        translated = _translate_structured(self._enriched)
        return {"translated_newsletter": translated}


def _base_state(enriched_json, enriched_md, translation_dir, language):
    return {
        OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY: language,
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


async def _run_translate_node(tmp_path, language, enriched_dict):
    consolidated = tmp_path / "consolidated"
    enrichment_dir = str(consolidated / "link_enrichment")
    translation_dir = str(consolidated / "final")
    os.makedirs(translation_dir, exist_ok=True)

    enriched_json, enriched_md = write_enriched_stage(enrichment_dir, enriched_dict)
    state = _base_state(enriched_json, enriched_md, translation_dir, language)

    fake = _FakeContentGenerator(enriched_dict, str(SummaryFormats.LANGTALKS_FORMAT))
    with patch(f"{FACTORY_PATH}.create", return_value=fake):
        result = await consolidation_nodes.translate_consolidated_newsletter(state, None)

    return result, translation_dir


@pytest.mark.asyncio
async def test_consolidated_english_writes_final_triplet(tmp_path):
    """English consolidated run writes the triplet and sets CONSOLIDATED_FINAL_HTML_PATH."""
    enriched_dict = make_enriched_newsletter_dict()
    result, translation_dir = await _run_translate_node(tmp_path, "english", enriched_dict)

    md = os.path.join(translation_dir, "final_newsletter.md")
    html = os.path.join(translation_dir, "final_newsletter.html")
    js = os.path.join(translation_dir, "final_newsletter.json")

    for p in (md, html, js):
        assert os.path.exists(p), f"final triplet member missing for English target: {p}"
        assert os.path.getsize(p) > 0, f"final triplet member empty for English target: {p}"

    assert result.get(OrchestratorKeys.CONSOLIDATED_FINAL_HTML_PATH) == html, "English run did not set CONSOLIDATED_FINAL_HTML_PATH to the final html"

    # English renders from the enriched dict directly (no LLM), so all enriched
    # content links are present.
    with open(html, encoding="utf-8") as f:
        html_text = f.read()
    from ._final_triplet_helpers import ENRICHED_CONTENT_URLS

    for url in ENRICHED_CONTENT_URLS:
        assert url in set(content_hrefs(html_text)), f"English final html dropped enriched link: {url}"


def test_consolidated_english_email_uses_consolidated_not_perchat(tmp_path):
    """With consolidated + per-chat final htmls present, resolver picks the consolidated one."""
    consolidated_final = tmp_path / "consolidated" / "final" / "final_newsletter.html"
    perchat_final = tmp_path / "per_chat" / "LangTalks" / "final" / "final_newsletter.html"
    for p in (consolidated_final, perchat_final):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<html><body>x</body></html>", encoding="utf-8")

    state = {OrchestratorKeys.CONSOLIDATED_FINAL_HTML_PATH: str(consolidated_final)}
    chat_results = [{SingleChatKeys.FINAL_NEWSLETTER_HTML_PATH: str(perchat_final)}]

    resolved = consolidator_graph._find_best_html_path(state, chat_results=chat_results)

    assert resolved == str(consolidated_final), f"resolver must prefer the consolidated final html, got: {resolved}"


@pytest.mark.asyncio
async def test_final_json_preserves_enrichment_metadata_all_languages(tmp_path):
    """Non-English final json retains enrichment-only keys (parity with English)."""
    enriched_dict = make_enriched_newsletter_dict()
    enriched_dict.update(ENRICHMENT_ONLY_KEYS)

    _result, translation_dir = await _run_translate_node(tmp_path, "hebrew", enriched_dict)

    final_json = os.path.join(translation_dir, "final_newsletter.json")
    with open(final_json, encoding="utf-8") as f:
        final_dict = json.load(f)

    # The enrichment-only top-level keys survive into the non-English final json.
    for key, expected in ENRICHMENT_ONLY_KEYS.items():
        assert key in final_dict, f"non-English final json dropped enrichment-only key: {key}"
        assert final_dict[key] == expected, f"enrichment-only key value not preserved: {key}"

    # And the translated text still landed (translation actually ran).
    assert TARGET_LANG_TOKEN in final_dict[NSK.PRIMARY_DISCUSSION][NSK.TITLE], "translation did not run for non-English target"
