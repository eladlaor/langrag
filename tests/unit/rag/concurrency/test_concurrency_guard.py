"""Unit tests for the process-wide RAG concurrency guard.

Runs WITHOUT Docker. Each test sets the cap via the (lru_cached) settings
singleton and calls ``guard._reset_for_tests()`` so the guard rebuilds against
the patched cap and binds to the running event loop.
"""

import asyncio

import pytest

from config import get_settings
from rag.concurrency import guard
from rag.concurrency.guard import RagCapacityExceeded


@pytest.fixture
def set_cap(monkeypatch):
    """Return a setter that patches max_concurrent_requests and resets the guard."""

    def _set(cap: int) -> None:
        monkeypatch.setattr(get_settings().rag, "max_concurrent_requests", cap, raising=False)
        guard._reset_for_tests()

    yield _set
    guard._reset_for_tests()


async def test_acquire_up_to_cap_succeeds(set_cap):
    set_cap(3)
    assert await guard.try_acquire() is True
    assert await guard.try_acquire() is True
    assert await guard.try_acquire() is True
    assert guard.current_in_flight() == 3


async def test_acquire_beyond_cap_returns_false(set_cap):
    set_cap(2)
    assert await guard.try_acquire() is True
    assert await guard.try_acquire() is True
    # Third acquire must return False IMMEDIATELY (non-blocking): wrap in a tight
    # timeout and assert it does not block.
    result = await asyncio.wait_for(guard.try_acquire(), timeout=0.1)
    assert result is False


async def test_release_frees_a_slot(set_cap):
    set_cap(1)
    assert await guard.try_acquire() is True
    assert await guard.try_acquire() is False
    guard.release()
    assert await guard.try_acquire() is True


async def test_rag_slot_context_manager_releases_on_success(set_cap):
    set_cap(1)
    async with guard.rag_slot():
        # Inside the block the single slot is held; a concurrent acquire fails.
        assert await guard.try_acquire() is False
    assert guard.current_in_flight() == 0


async def test_rag_slot_releases_on_exception(set_cap):
    set_cap(1)
    with pytest.raises(ValueError):
        async with guard.rag_slot():
            raise ValueError("boom")
    assert guard.current_in_flight() == 0
    # Slot is reusable after the exception path released it in finally.
    assert await guard.try_acquire() is True


async def test_rag_slot_raises_capacity_exceeded_when_full(set_cap):
    set_cap(1)
    assert await guard.try_acquire() is True
    with pytest.raises(RagCapacityExceeded) as exc:
        async with guard.rag_slot():
            pass
    assert exc.value.cap == 1
    assert exc.value.in_flight == 1


async def test_capacity_reflects_settings(set_cap):
    set_cap(7)
    assert guard.capacity() == 7


async def test_concurrent_tasks_respect_cap(set_cap):
    set_cap(5)
    hold = asyncio.Event()
    acquired = 0
    rejected = 0

    async def worker():
        nonlocal acquired, rejected
        try:
            async with guard.rag_slot():
                acquired += 1
                await hold.wait()
        except RagCapacityExceeded:
            rejected += 1

    tasks = [asyncio.create_task(worker()) for _ in range(20)]
    # Let the tasks run until they either acquire-and-block or get rejected.
    await asyncio.sleep(0.05)
    assert acquired == 5
    assert rejected == 15
    hold.set()
    await asyncio.gather(*tasks)
    assert guard.current_in_flight() == 0
