"""COST-5: the concurrency guard supports a per-process cap OVERRIDE so the MCP
process can run a lower cap than the REST app without lowering the app's setting.
"""

import pytest

from config import get_settings
from rag.concurrency import guard


@pytest.fixture(autouse=True)
def _reset():
    guard._reset_for_tests()
    yield
    guard._reset_for_tests()


async def test_override_wins_over_settings(monkeypatch):
    monkeypatch.setattr(get_settings().rag, "max_concurrent_requests", 50, raising=False)
    guard.configure_cap(6)
    assert guard.capacity() == 6
    # Acquire exactly the override count, then reject.
    for _ in range(6):
        assert await guard.try_acquire() is True
    assert await guard.try_acquire() is False


async def test_falls_back_to_settings_without_override(monkeypatch):
    monkeypatch.setattr(get_settings().rag, "max_concurrent_requests", 9, raising=False)
    guard._reset_for_tests()
    assert guard.capacity() == 9
