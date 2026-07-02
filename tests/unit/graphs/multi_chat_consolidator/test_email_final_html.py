"""
TDD (failing-first) tests for EMAIL html resolution against the final triplet.

Spec: knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md (Part A, steps 3
and Design Decisions "html at final stage only").

Target behavior locked here:
  * _find_best_html_path returns the FINAL html path when it exists.
  * Generation and enrichment stage dirs contain NO .html (only md+json);
    html exists ONLY in the final dir.
  * With no final html present, the send path fails loud (fail-fast) rather
    than falling back to a pre-enrichment draft html.

These MUST fail against current code, which resolves email html by swapping
`.md`->`.html` on the enriched/base md path (a draft) and returns that draft.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from constants import (
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_LINK_ENRICHMENT,
    DIR_NAME_NEWSLETTER,
    FILE_EXT_HTML,
)
from graphs.state_keys import OrchestratorKeys
from graphs.multi_chat_consolidator import graph as consolidator_graph

# The target state key for the final html path (Part A step 2). Referenced
# defensively so an as-yet-unadded key does not break collection of the whole
# module; when absent, getattr returns None and the write below is skipped,
# which makes the "final html present" tests fail for the right reason.
FINAL_HTML_KEY = getattr(OrchestratorKeys, "CONSOLIDATED_FINAL_HTML_PATH", None)
FINAL_MD_KEY = getattr(OrchestratorKeys, "CONSOLIDATED_FINAL_MD_PATH", None)


def _layout_stage_dirs(tmp_path):
    """Create the consolidated stage tree with a draft html + a final html.

    generation/enrichment dirs get md+json ONLY (no html, per the new rule).
    The final dir gets the full triplet including html.
    """
    consolidated = tmp_path / DIR_NAME_CONSOLIDATED
    newsletter_dir = consolidated / DIR_NAME_NEWSLETTER
    enrichment_dir = consolidated / DIR_NAME_LINK_ENRICHMENT
    final_dir = consolidated / "final_newsletter"
    for d in (newsletter_dir, enrichment_dir, final_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Generation + enrichment: md + json only.
    (newsletter_dir / "consolidated_newsletter.md").write_text("draft md", encoding="utf-8")
    (newsletter_dir / "consolidated_newsletter.json").write_text("{}", encoding="utf-8")
    (enrichment_dir / "enriched_consolidated.md").write_text("enriched md", encoding="utf-8")
    (enrichment_dir / "enriched_consolidated.json").write_text("{}", encoding="utf-8")

    # Final: full triplet.
    final_html = final_dir / "final_newsletter.html"
    (final_dir / "final_newsletter.md").write_text("final md", encoding="utf-8")
    (final_dir / "final_newsletter.json").write_text("{}", encoding="utf-8")
    final_html.write_text("<html><body>FINAL enriched translated</body></html>", encoding="utf-8")

    return {
        "newsletter_dir": str(newsletter_dir),
        "enrichment_dir": str(enrichment_dir),
        "final_dir": str(final_dir),
        "final_html": str(final_html),
    }


def _state_with_final(layout):
    """Orchestrator state whose paths point at the stage tree above."""
    state = {
        OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH: os.path.join(layout["enrichment_dir"], "enriched_consolidated.md"),
        OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH: os.path.join(layout["newsletter_dir"], "consolidated_newsletter.md"),
    }
    if FINAL_HTML_KEY is not None:
        state[FINAL_HTML_KEY] = layout["final_html"]
    if FINAL_MD_KEY is not None:
        state[FINAL_MD_KEY] = os.path.join(layout["final_dir"], "final_newsletter.md")
    return state


def test_email_uses_final_html(tmp_path):
    """_find_best_html_path resolves the FINAL html, never a stage draft."""
    layout = _layout_stage_dirs(tmp_path)
    state = _state_with_final(layout)

    resolved = consolidator_graph._find_best_html_path(state, chat_results=[])

    assert resolved == layout["final_html"], f"email html should be the final triplet html, got: {resolved}"


def test_no_intermediate_html(tmp_path):
    """Generation + enrichment dirs contain NO html; html exists ONLY in final dir."""
    layout = _layout_stage_dirs(tmp_path)

    for stage_dir in (layout["newsletter_dir"], layout["enrichment_dir"]):
        htmls = [f for f in os.listdir(stage_dir) if f.endswith(FILE_EXT_HTML)]
        assert htmls == [], f"intermediate stage dir must not contain html: {stage_dir} has {htmls}"

    final_htmls = [f for f in os.listdir(layout["final_dir"]) if f.endswith(FILE_EXT_HTML)]
    assert final_htmls == ["final_newsletter.html"], f"final dir must hold exactly the final html, got {final_htmls}"

    # And resolution must land on that final html (not a swapped-md draft).
    resolved = consolidator_graph._find_best_html_path(_state_with_final(layout), chat_results=[])
    assert resolved == layout["final_html"]


def test_email_fails_loud_without_final_html(tmp_path):
    """With no final html, resolution must NOT return a pre-enrichment draft.

    The new rule removes the enriched/base `.md`->`.html` fallbacks, so when the
    final html is missing the resolver yields nothing usable and the send path
    fails fast. We assert no draft path is returned.
    """
    consolidated = tmp_path / DIR_NAME_CONSOLIDATED
    newsletter_dir = consolidated / DIR_NAME_NEWSLETTER
    enrichment_dir = consolidated / DIR_NAME_LINK_ENRICHMENT
    for d in (newsletter_dir, enrichment_dir):
        d.mkdir(parents=True, exist_ok=True)

    # A pre-enrichment DRAFT html deliberately exists on disk (the buggy
    # fallback target). The new resolver must ignore it.
    draft_md = newsletter_dir / "consolidated_newsletter.md"
    draft_md.write_text("draft md", encoding="utf-8")
    draft_html = newsletter_dir / "consolidated_newsletter.html"
    draft_html.write_text("<html>DRAFT</html>", encoding="utf-8")

    enriched_md = enrichment_dir / "enriched_consolidated.md"
    enriched_md.write_text("enriched md", encoding="utf-8")
    enriched_html = enrichment_dir / "enriched_consolidated.html"
    enriched_html.write_text("<html>ENRICHED DRAFT</html>", encoding="utf-8")

    state = {
        OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH: str(enriched_md),
        OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH: str(draft_md),
        # No final html key set -> nothing to resolve.
    }
    if FINAL_HTML_KEY is not None:
        state[FINAL_HTML_KEY] = None

    resolved = consolidator_graph._find_best_html_path(state, chat_results=[])

    assert resolved not in (str(draft_html), str(enriched_html)), "resolver silently fell back to a pre-enrichment draft html"
    assert not resolved, f"with no final html, resolver must yield nothing (fail-fast), got: {resolved}"
