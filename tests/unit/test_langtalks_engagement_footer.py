"""Regression tests for the LangTalks engagement-stats attribution footer.

Covers the extended footer that surfaces total message count + unique-participant
count alongside the existing source-group/start-time attribution, and the rule that
a merged discussion's start time is the earliest timestamp among its source groups.
"""

from custom_types.newsletter_formats.langtalks.renderer import LangTalksRenderer

HEBREW = "hebrew"
ENGLISH = "english"


def _single_source_discussion() -> dict:
    return {
        "title": "T",
        "bullet_points": [{"label": "a", "content": "b"}],
        "first_message_timestamp": 1781376544000,
        "chat_name": "LangTalks Community 4",
        "number_of_messages": 16,
        "number_of_unique_participants": 9,
    }


def _merged_discussion() -> dict:
    return {
        "title": "T",
        "bullet_points": [{"label": "a", "content": "b"}],
        "is_merged": True,
        "number_of_messages": 24,
        "number_of_unique_participants": 10,
        "source_discussions": [
            {"group": "LangTalks Community 3", "first_message_timestamp": 1782708773000},
            {"group": "LangTalks Community 5", "first_message_timestamp": 1782800000000},
        ],
    }


def test_single_source_footer_includes_engagement_stats():
    renderer = LangTalksRenderer()
    html = renderer._render_discussion_attribution_html(_single_source_discussion(), HEBREW)
    assert "16" in html and "9" in html
    assert "LangTalks Community 4" in html
    assert "משתתפים" in html


def test_merged_footer_lists_all_groups_with_total_counts():
    renderer = LangTalksRenderer()
    html = renderer._render_discussion_attribution_html(_merged_discussion(), HEBREW)
    assert "LangTalks Community 3" in html
    assert "LangTalks Community 5" in html
    # Totals, not per-group sums computed at render time.
    assert "24" in html and "10" in html


def test_merged_start_time_uses_earliest_source_timestamp():
    renderer = LangTalksRenderer()
    earliest = renderer._earliest_source_timestamp(_merged_discussion())
    assert earliest == 1782708773000
    time_str, date_str = renderer._format_timestamp(earliest)
    html = renderer._render_discussion_attribution_html(_merged_discussion(), HEBREW)
    assert time_str in html and date_str in html
    # The later timestamp must not be the one rendered as the start time.
    later_time, _ = renderer._format_timestamp(1782800000000)
    assert f"{later_time} |" not in html


def test_markdown_attribution_includes_engagement_stats():
    renderer = LangTalksRenderer()
    md = renderer._render_markdown_attribution(_single_source_discussion(), ENGLISH)
    assert "16 messages" in md
    assert "9 participants" in md


def test_footer_omitted_when_no_counts_present():
    renderer = LangTalksRenderer()
    disc = {"title": "T", "first_message_timestamp": 0}
    assert renderer._render_engagement_stats(disc, HEBREW) == ""
