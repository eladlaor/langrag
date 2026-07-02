"""Pure-unit regression tests for RunTracker fail-soft boundaries.

These guard two fixes and need no MongoDB (the runs repo is mocked):

1. `update_run_diagnostics` returns the bool from `BaseRepository.update_one`
   directly (it used to read `.modified_count` on that bool, raising
   AttributeError that the broad `except Exception` then swallowed).
2. The fail-soft `except` clauses are narrowed to `PyMongoError`, so a
   programmer error (AttributeError/TypeError) propagates instead of being
   logged-and-ignored, while expected DB errors stay fail-soft.

The DB round-trip companion lives in `tests/unit/db/test_run_tracker_roundtrip.py`
(it requires the real MongoDB fixture).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pymongo.errors import OperationFailure

from custom_types.db_schemas import MessageDocument
from custom_types.field_keys import DbFieldKeys, DecryptionResultKeys, DiscussionKeys, MessageSourceKeys
from db.run_tracker import RunTracker


def _tracker_with_mock_repo(runs_repo: AsyncMock) -> RunTracker:
    """Build a RunTracker with its runs repo mocked and init short-circuited."""
    tracker = RunTracker()
    tracker._initialized = True
    tracker._runs_repo = runs_repo
    return tracker


def _tracker_with_mock_messages_repo(messages_repo: AsyncMock) -> RunTracker:
    """Build a RunTracker with its messages repo mocked and init short-circuited."""
    tracker = RunTracker()
    tracker._initialized = True
    tracker._messages_repo = messages_repo
    return tracker


async def test_update_run_diagnostics_returns_persisted_bool():
    """A successful persist returns True (the bool from update_one)."""
    runs_repo = AsyncMock()
    runs_repo.update_one.return_value = True
    tracker = _tracker_with_mock_repo(runs_repo)

    result = await tracker.update_run_diagnostics("run-1", {"summary": "ok"})

    assert result is True
    runs_repo.update_one.assert_awaited_once()


async def test_update_run_diagnostics_propagates_programmer_error():
    """A coding bug (AttributeError) must NOT be swallowed by fail-soft."""
    runs_repo = AsyncMock()
    runs_repo.update_one.side_effect = AttributeError("bool has no modified_count")
    tracker = _tracker_with_mock_repo(runs_repo)

    with pytest.raises(AttributeError):
        await tracker.update_run_diagnostics("run-1", {"summary": "ok"})


async def test_update_run_diagnostics_fail_soft_on_db_error():
    """An expected DB error (PyMongoError subclass) stays fail-soft -> False."""
    runs_repo = AsyncMock()
    runs_repo.update_one.side_effect = OperationFailure("transient db error")
    tracker = _tracker_with_mock_repo(runs_repo)

    result = await tracker.update_run_diagnostics("run-1", {"summary": "ok"})

    assert result is False


async def test_complete_run_propagates_programmer_error():
    """complete_run also lets programmer errors propagate."""
    runs_repo = AsyncMock()
    runs_repo.complete_run.side_effect = TypeError("unexpected kwarg")
    tracker = _tracker_with_mock_repo(runs_repo)

    with pytest.raises(TypeError):
        await tracker.complete_run("run-1", "/tmp/out", {"cost": 1.0})


async def test_complete_run_fail_soft_on_db_error():
    """complete_run stays fail-soft on an expected DB error."""
    runs_repo = AsyncMock()
    runs_repo.complete_run.side_effect = OperationFailure("transient db error")
    tracker = _tracker_with_mock_repo(runs_repo)

    result = await tracker.complete_run("run-1", "/tmp/out", {"cost": 1.0})

    assert result is False


async def test_complete_run_passes_metrics_in_single_call():
    """Metrics go through the repo's complete_run, not a second update_one."""
    runs_repo = AsyncMock()
    runs_repo.complete_run.return_value = True
    tracker = _tracker_with_mock_repo(runs_repo)
    metrics = {"cost_usd": 0.42, "tokens": 1234}

    result = await tracker.complete_run("run-1", "/tmp/out", metrics)

    assert result is True
    runs_repo.complete_run.assert_awaited_once_with("run-1", "/tmp/out", metrics)
    runs_repo.update_one.assert_not_awaited()


# ---------------------------------------------------------------------------
# store_raw_messages content coercion (regression: image/poll messages carry a
# dict `content` that broke MessageDocument validation -> whole chat failed).
# ---------------------------------------------------------------------------


async def test_store_raw_messages_persists_text_and_image_content():
    """A text message (str content) and an image message (dict content) both
    yield valid MessageDocuments with `content` flattened to the expected str.

    Guards the bug where a dict `content` ({"body": ..., "msgtype": "m.image"})
    raised a Pydantic `string_type` validation error, failing extract_messages
    for every chat that contained an image.
    """
    messages_repo = AsyncMock()
    messages_repo.insert_batch.return_value = 2
    tracker = _tracker_with_mock_messages_repo(messages_repo)

    raw_messages = [
        {
            DiscussionKeys.ID: "evt_text",
            MessageSourceKeys.SENDER_ID: "user_1",
            MessageSourceKeys.TIMESTAMP: 1_700_000_000_000,
            MessageSourceKeys.CONTENT: "hello world",
        },
        {
            DiscussionKeys.ID: "evt_image",
            MessageSourceKeys.SENDER_ID: "user_2",
            MessageSourceKeys.TIMESTAMP: 1_700_000_001_000,
            MessageSourceKeys.CONTENT: {DecryptionResultKeys.BODY: "photo.jpg", DecryptionResultKeys.MSGTYPE: "m.image"},
        },
    ]

    count = await tracker.store_raw_messages(run_id="run-1", chat_name="LangTalks Community", data_source_name="langtalks", messages=raw_messages)

    assert count == 2
    messages_repo.insert_batch.assert_awaited_once()

    persisted_docs = messages_repo.insert_batch.await_args.args[0]
    assert len(persisted_docs) == 2

    # Every persisted doc must round-trip through the canonical schema with a str content.
    for doc in persisted_docs:
        validated = MessageDocument(**doc)
        assert isinstance(validated.content, str)

    contents = [doc[DbFieldKeys.CONTENT] for doc in persisted_docs]
    assert contents == ["hello world", "photo.jpg"]
