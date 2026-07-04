"""Anonymous-lane admission stack tests (no Docker).

Covers enforce_anonymous_admission's three guards (per-IP rate limit, per-IP
daily quota, anonymous global breaker) and the principal routing inside
search_podcasts (anonymous ids -> anonymous stack, keyed ids -> keyed stack,
both -> shared global embed breaker).
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

from unittest.mock import AsyncMock, MagicMock

import pytest

from constants import (
    RAG_GLOBAL_ANON_QUOTA_KEY_ID,
    RAG_REJECT_REASON_ANON_GLOBAL_BREAKER,
)
from rag.mcp import tools as mcp_tools
from rag.quota import admission
from rag.quota.admission import (
    ADMISSION_REASON_DAILY_QUOTA,
    ADMISSION_REASON_RATE_LIMIT,
    QueryAdmissionError,
    enforce_anonymous_admission,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from config import get_settings

    get_settings.cache_clear()
    admission._reset_for_tests()
    yield
    get_settings.cache_clear()
    admission._reset_for_tests()


class _FakeQuotaRepo:
    """Records (key, limit) calls; per-key allow/deny is scripted via deny_keys."""

    def __init__(self, deny_keys: set[str] | None = None):
        self.calls: list[tuple[str, int]] = []
        self.deny_keys = deny_keys or set()

    async def check_and_increment_key(self, key_id: str, *, limit: int) -> bool:
        self.calls.append((key_id, limit))
        return key_id not in self.deny_keys


# ---- enforce_anonymous_admission ------------------------------------------------


async def test_admits_and_consumes_ip_then_global(monkeypatch):
    repo = _FakeQuotaRepo()
    await enforce_anonymous_admission("anon:abc123", quota_repo=repo)

    from config import get_settings

    rag = get_settings().rag
    assert repo.calls == [
        ("anon:abc123", rag.mcp_anon_max_queries_per_ip_per_day),
        (RAG_GLOBAL_ANON_QUOTA_KEY_ID, rag.mcp_anon_global_daily_max),
    ]


async def test_anon_rate_limit_trips_first(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANON_QUERY_RATE_PER_MIN", "2")
    from config import get_settings

    get_settings.cache_clear()
    admission._reset_for_tests()

    repo = _FakeQuotaRepo()
    await enforce_anonymous_admission("anon:rate", quota_repo=repo)
    await enforce_anonymous_admission("anon:rate", quota_repo=repo)
    with pytest.raises(QueryAdmissionError) as exc:
        await enforce_anonymous_admission("anon:rate", quota_repo=repo)
    assert exc.value.reason == ADMISSION_REASON_RATE_LIMIT
    # The shed request never reached the DB-backed quota counters.
    assert len(repo.calls) == 4


async def test_anon_ip_quota_trips_with_daily_reason():
    repo = _FakeQuotaRepo(deny_keys={"anon:over"})
    with pytest.raises(QueryAdmissionError) as exc:
        await enforce_anonymous_admission("anon:over", quota_repo=repo)
    assert exc.value.reason == ADMISSION_REASON_DAILY_QUOTA
    # The global sentinel was NOT consumed on the rejected path.
    assert repo.calls == [(repo.calls[0][0], repo.calls[0][1])]


async def test_anon_global_breaker_trips_with_its_own_reason():
    repo = _FakeQuotaRepo(deny_keys={RAG_GLOBAL_ANON_QUOTA_KEY_ID})
    with pytest.raises(QueryAdmissionError) as exc:
        await enforce_anonymous_admission("anon:ok", quota_repo=repo)
    assert exc.value.reason == RAG_REJECT_REASON_ANON_GLOBAL_BREAKER


async def test_distinct_ips_have_independent_rate_buckets(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANON_QUERY_RATE_PER_MIN", "1")
    from config import get_settings

    get_settings.cache_clear()
    admission._reset_for_tests()

    repo = _FakeQuotaRepo()
    await enforce_anonymous_admission("anon:ip-a", quota_repo=repo)
    # A different IP-derived id is NOT throttled by ip-a's consumption.
    await enforce_anonymous_admission("anon:ip-b", quota_repo=repo)
    with pytest.raises(QueryAdmissionError):
        await enforce_anonymous_admission("anon:ip-a", quota_repo=repo)


# ---- search_podcasts principal routing -------------------------------------------


def _stub_retrieval(captured: dict):
    async def _fake_retrieve(self, *args, **kwargs):
        captured["__retrieved__"] = True
        return {
            "context": "ctx",
            "citations": [{"index": 0}],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }

    return _fake_retrieve


@pytest.fixture
def _patched_tools(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _stub_retrieval(captured))
    monkeypatch.setattr(mcp_tools, "flush_langfuse", lambda: None)
    monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, None))
    monkeypatch.setattr(mcp_tools, "_get_quota_repo", AsyncMock(return_value=MagicMock()))
    return captured


async def test_anonymous_principal_routes_to_anonymous_stack(_patched_tools, monkeypatch):
    monkeypatch.setattr(mcp_tools, "resolve_current_key_id", lambda: "anon:abc123")
    p_anon = AsyncMock()
    p_keyed = AsyncMock()
    p_breaker = AsyncMock()
    monkeypatch.setattr(mcp_tools, "enforce_anonymous_admission", p_anon)
    monkeypatch.setattr(mcp_tools, "enforce_query_admission", p_keyed)
    monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", p_breaker)

    await mcp_tools.search_podcasts(query="q")

    p_anon.assert_awaited_once()
    p_keyed.assert_not_awaited()
    # The anonymous lane still consumes the SHARED embed breaker.
    p_breaker.assert_awaited_once()
    assert _patched_tools["__retrieved__"] is True


async def test_keyed_principal_routes_to_keyed_stack(_patched_tools, monkeypatch):
    monkeypatch.setattr(mcp_tools, "resolve_current_key_id", lambda: "consumer-1")
    p_anon = AsyncMock()
    p_keyed = AsyncMock()
    monkeypatch.setattr(mcp_tools, "enforce_anonymous_admission", p_anon)
    monkeypatch.setattr(mcp_tools, "enforce_query_admission", p_keyed)
    monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", AsyncMock())

    await mcp_tools.search_podcasts(query="q")

    p_keyed.assert_awaited_once()
    p_anon.assert_not_awaited()


async def test_anonymous_rejection_stops_before_retrieval(_patched_tools, monkeypatch):
    monkeypatch.setattr(mcp_tools, "resolve_current_key_id", lambda: "anon:abc123")
    monkeypatch.setattr(
        mcp_tools,
        "enforce_anonymous_admission",
        AsyncMock(side_effect=QueryAdmissionError("over", reason=ADMISSION_REASON_DAILY_QUOTA)),
    )
    monkeypatch.setattr(mcp_tools, "check_global_embed_breaker", AsyncMock())
    p_reject = MagicMock()
    monkeypatch.setattr(mcp_tools, "emit_reject", p_reject)

    with pytest.raises(QueryAdmissionError):
        await mcp_tools.search_podcasts(query="q")

    # Retrieval (and its owner-paid embedding) was NEVER reached; reject observed.
    assert "__retrieved__" not in _patched_tools
    p_reject.assert_called_once()
    assert p_reject.call_args.kwargs["key_id"] == "anon:abc123"
