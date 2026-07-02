"""
TDD (failing-first) tests for the RunsBrowser newsletter reader vs the numbered
final-newsletter layout, plus legacy backward-compat.

Spec: knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md
      - Blast Radius: repoint the consolidated html read to the FINAL dir
        (final_newsletter.html).
      - Backward Compatibility / Decision 3: readers probe the new dir name
        first, then the legacy name, and use whichever exists.

Target behavior locked here:
  * test_runs_browser_reads_final_newsletter (RED now): the reader resolves a
    run laid out with the NEW numbered final dir
    (consolidated/05_final_newsletter/final_newsletter.html). The current reader
    only knows newsletter/, link_enrichment/, final_translation/ and returns
    None -> fails today.
  * test_runs_browser_reads_legacy_dirs (regression guard): the reader still
    resolves a run laid out with the OLD un-numbered names
    (consolidated/final_translation/*_translated_summary.html). Green today;
    guards against the refactor dropping the legacy fallback.
"""

from __future__ import annotations

import os

from constants import DIR_NAME_CONSOLIDATED, FileFormat, NewsletterType
from api.observability.runs import _resolve_and_read_newsletter

# New numbered final stage dir + canonical final filename (Part A + Part B).
NEW_FINAL_DIR = "05_final_newsletter"
NEW_FINAL_HTML = "final_newsletter.html"

# Legacy (pre-refactor) consolidated final layout.
LEGACY_FINAL_DIR = "final_translation"
LEGACY_FINAL_HTML = "Consolidated_translated_summary.html"


def _make_run_dir(tmp_path, final_dir_name: str, final_file_name: str, body: str) -> str:
    run_dir = tmp_path / "langtalks_2026-06-01_to_2026-07-01"
    final_dir = run_dir / DIR_NAME_CONSOLIDATED / final_dir_name
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / final_file_name).write_text(body, encoding="utf-8")
    return str(run_dir)


def test_runs_browser_reads_final_newsletter(tmp_path):
    """Reader resolves the NEW numbered final dir + final_newsletter.html."""
    body = "<html><body>FINAL enriched translated newsletter</body></html>"
    run_dir = _make_run_dir(tmp_path, NEW_FINAL_DIR, NEW_FINAL_HTML, body)

    content_path, content, _direction = _resolve_and_read_newsletter(run_dir, NewsletterType.CONSOLIDATED, FileFormat.HTML)

    assert content_path is not None, "reader did not resolve the numbered final_newsletter dir"
    assert content_path.endswith(os.path.join(NEW_FINAL_DIR, NEW_FINAL_HTML)), f"reader resolved a non-final artifact: {content_path}"
    assert content == body


def test_runs_browser_reads_legacy_dirs(tmp_path):
    """Reader still resolves the OLD un-numbered final_translation layout."""
    body = "<html><body>LEGACY translated newsletter</body></html>"
    run_dir = _make_run_dir(tmp_path, LEGACY_FINAL_DIR, LEGACY_FINAL_HTML, body)

    content_path, content, _direction = _resolve_and_read_newsletter(run_dir, NewsletterType.CONSOLIDATED, FileFormat.HTML)

    assert content_path is not None, "reader lost the legacy final_translation fallback"
    assert content_path.endswith(LEGACY_FINAL_HTML)
    assert content == body
