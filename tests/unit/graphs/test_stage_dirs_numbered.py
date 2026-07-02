"""
TDD (failing-first) tests for NUMBERED STAGE SUBDIRS.

Spec: knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md (Part B).

Target: each stage output dir name is prefixed with its zero-padded pipeline
order, so a directory listing reads as the pipeline order.

  Consolidated:  01_aggregated_discussions, 02_discussions_ranking,
                 03_newsletter, 04_link_enrichment, 05_final_newsletter
  Per-chat:      01_extracted, 03_preprocessed, 04_translated,
                 05_separate_discussions, 06_discussions_ranking,
                 07_newsletter, 08_link_enrichment, 09_final_newsletter
                 (02_images is optional and absent when image extraction is off)

These MUST fail against current code, which creates un-numbered dir names
(`aggregated_discussions`, `newsletter`, `final_translation`, `extracted`, ...).
"""

from __future__ import annotations

import os

from graphs.state_keys import OrchestratorKeys, SingleChatKeys

from graphs.multi_chat_consolidator.consolidation_nodes import setup_consolidated_directories
from graphs.single_chat_analyzer.graph import setup_directories

# Target dir names, in pipeline order (values only; constant NAMES are stable).
EXPECTED_CONSOLIDATED_DIRS = [
    "01_aggregated_discussions",
    "02_discussions_ranking",
    "03_newsletter",
    "04_link_enrichment",
    "05_final_newsletter",
]

# Per-chat: the mandatory (non-optional) stage dirs. 02_images is skipped when
# image extraction is off, so we assert on the numbered non-image stages.
EXPECTED_PER_CHAT_DIRS = [
    "01_extracted",
    "03_preprocessed",
    "04_translated",
    "05_separate_discussions",
    "06_discussions_ranking",
    "07_newsletter",
    "08_link_enrichment",
    "09_final_newsletter",
]


def test_stage_dirs_numbered_consolidated(tmp_path):
    """Consolidated setup creates the zero-padded numbered stage dirs."""
    base = str(tmp_path)
    setup_consolidated_directories({OrchestratorKeys.BASE_OUTPUT_DIR: base}, None)

    consolidated = os.path.join(base, "consolidated")
    created = set(os.listdir(consolidated))

    missing = [d for d in EXPECTED_CONSOLIDATED_DIRS if d not in created]
    assert not missing, f"consolidated stage dirs not numbered per pipeline order; missing {missing}, got {sorted(created)}"


def test_stage_dirs_numbered_per_chat(tmp_path):
    """Per-chat setup creates the zero-padded numbered stage dirs."""
    base = str(tmp_path)
    state = {
        SingleChatKeys.CHAT_NAME: "LangTalks Community",
        SingleChatKeys.OUTPUT_DIR: base,
        SingleChatKeys.START_DATE: "2026-06-01",
        SingleChatKeys.END_DATE: "2026-07-01",
        SingleChatKeys.WORKFLOW_NAME: "generate_periodic_newsletter",
        SingleChatKeys.DESIRED_LANGUAGE_FOR_SUMMARY: "english",
    }
    setup_directories(state, None)

    created = set(os.listdir(base))
    missing = [d for d in EXPECTED_PER_CHAT_DIRS if d not in created]
    assert not missing, f"per-chat stage dirs not numbered per pipeline order; missing {missing}, got {sorted(created)}"
