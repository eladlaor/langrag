"""Verify-endpoint rate-limit test (C3) — no Docker.

verify mints a credential, so it MUST be throttled like request-key. This drives
a real FastAPI app + TestClient so app.state.limiter activates the decorator, and
asserts the over-limit burst returns 429. The limiter check runs BEFORE the
handler body, so no real Mongo is needed (allowed calls are stubbed to a 400).
"""

import importlib
import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


def _reload_rate_limiting():
    from config import get_settings

    get_settings.cache_clear()
    import api.rate_limiting as rl

    return importlib.reload(rl)


def test_verify_endpoint_is_rate_limited(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    rl = _reload_rate_limiting()

    import api.podcast_consumers as mod

    mod = importlib.reload(mod)

    # Stub the DB + repos so allowed (non-429) calls resolve to a clean 400
    # (unknown token) instead of touching Mongo.
    async def _fake_db():
        return object()

    class _Consumers:
        def __init__(self, *a, **k):
            pass

        async def consume_token(self, token_hash):
            return None

        async def find_by_token_hash(self, token_hash):
            return None

    class _Keys:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(mod, "get_database", _fake_db)
    monkeypatch.setattr(mod, "PodcastApiConsumersRepository", _Consumers)
    monkeypatch.setattr(mod, "RAGApiKeysRepository", _Keys)

    from constants import ROUTE_PODCAST_CONSUMER_VERIFY

    app = FastAPI()
    rl.setup_rate_limiting(app)
    app.include_router(mod.router, prefix="/api")

    client = TestClient(app, raise_server_exceptions=False)

    verify_path = f"/api{ROUTE_PODCAST_CONSUMER_VERIFY}"
    limit = int(rl.RATE_PODCAST_CONSUMER_VERIFY.split("/")[0])
    payload = {"token": "does-not-matter"}

    statuses = [client.post(verify_path, json=payload).status_code for _ in range(limit + 2)]

    assert 429 in statuses, statuses
    assert statuses[0] != 429  # first request is not the one that trips the limit
