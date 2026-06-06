"""Unit tests for HybridDecryptionManager failure accounting.

Regression guard for the audit finding that decryption failures were swallowed
at debug level with a permanently-empty `strategy_failures` counter. We assert
that per-strategy failures are now recorded and that an all-strategies-fail event
returns None (so the caller can drop or surface it) without raising.
"""

import pytest

from core.ingestion.decryption.hybrid_manager import (
    DecryptionStatistics,
    HybridDecryptionManager,
)


class _Strategy:
    """Minimal decryption strategy stub: optionally returns a result, raises, or
    returns None (could-not-decrypt)."""

    def __init__(self, name, *, result=None, raises=None):
        self._name = name
        self._result = result
        self._raises = raises

    def get_strategy_name(self):
        return self._name

    async def initialize(self):
        return None

    async def cleanup(self):
        return None

    async def decrypt_message(self, encrypted_event, room_id):
        if self._raises is not None:
            raise self._raises
        return self._result


ENCRYPTED_EVENT = {"type": "m.room.encrypted", "event_id": "$evt"}


def test_record_failure_populates_strategy_counter():
    stats = DecryptionStatistics()
    stats.record_failure("manual_export")
    stats.record_failure("manual_export")
    stats.record_failure(None)  # unknown strategy -> totals only

    assert stats.total_failures == 3
    assert stats.strategy_failures == {"manual_export": 2}


@pytest.mark.asyncio
async def test_all_strategies_fail_records_per_strategy_and_returns_none():
    mgr = HybridDecryptionManager(
        strategies=[
            _Strategy("persistent", result=None),
            _Strategy("server_backup", raises=RuntimeError("no key")),
        ]
    )
    await mgr.initialize()

    result = await mgr.decrypt_message(ENCRYPTED_EVENT, room_id="!room:beeper.com")

    assert result is None
    summary = mgr.get_statistics()
    assert summary["total_failures"] == 1
    # The last strategy that failed is attributed in strategy_failures.
    assert summary["strategy_failures"].get("server_backup") == 1


@pytest.mark.asyncio
async def test_success_short_circuits_and_records_success():
    mgr = HybridDecryptionManager(
        strategies=[
            _Strategy("persistent", result={"body": "decrypted"}),
            _Strategy("server_backup", raises=AssertionError("must not be reached")),
        ]
    )
    await mgr.initialize()

    result = await mgr.decrypt_message(ENCRYPTED_EVENT, room_id="!room:beeper.com")

    assert result == {"body": "decrypted"}
    summary = mgr.get_statistics()
    assert summary["total_successes"] == 1
    assert summary["total_failures"] == 0
    assert summary["strategy_successes"].get("persistent") == 1
