"""COST-5: standalone SSE-connection cap helper.

A NEW standalone counter the MCP SSE auth middleware can import to bound
simultaneous SSE connections (the middleware body itself is owned elsewhere).
"""

import pytest

from config import get_settings
from rag.concurrency import sse_connections


@pytest.fixture(autouse=True)
def _reset():
    sse_connections._reset_for_tests()
    yield
    sse_connections._reset_for_tests()


async def test_admits_up_to_cap_then_rejects(monkeypatch):
    monkeypatch.setattr(get_settings().rag, "mcp_max_sse_connections", 2, raising=False)
    assert await sse_connections.try_open() is True
    assert await sse_connections.try_open() is True
    assert await sse_connections.try_open() is False


async def test_close_frees_capacity(monkeypatch):
    monkeypatch.setattr(get_settings().rag, "mcp_max_sse_connections", 1, raising=False)
    assert await sse_connections.try_open() is True
    assert await sse_connections.try_open() is False
    sse_connections.close()
    assert await sse_connections.try_open() is True
