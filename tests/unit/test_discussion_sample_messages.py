"""Unit tests for _first_last_sample in the discussion ranker.

Locks in the fix for the asymmetric slicing that dropped a single-message
discussion's content from the last-sample slot.
"""

from core.retrieval.rankers.discussion_ranker import _first_last_sample


def test_empty_messages_returns_empty_list():
    assert _first_last_sample([]) == []


def test_single_message_returns_single_content():
    assert _first_last_sample([{"content": "only"}]) == ["only"]


def test_multiple_messages_returns_first_and_last():
    msgs = [{"content": "first"}, {"content": "mid"}, {"content": "last"}]
    assert _first_last_sample(msgs) == ["first", "last"]


def test_missing_content_defaults_to_empty_string():
    assert _first_last_sample([{}]) == [""]
    assert _first_last_sample([{}, {}]) == ["", ""]
