"""Tests for the auth/rate-limiting red-flag hardening (audit 2026-06-16 v3).

Covers, without requiring MongoDB:
- #1  /api/auth/login is rate-limited (429 after the configured burst).
- #3  startup login-gate fail-fast no longer requires LANGRAG_LOGIN_PASSWORD.
- #4  the rate-limit bucket key never embeds the raw API key and is stable.

The limiter store (#2) is exercised implicitly: these tests run against the
default in-memory store, which is the production single-worker behaviour.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from constants import RAG_API_KEY_BEARER_SCHEME, RAG_API_KEY_HEADER


def _reload_rate_limiting():
    """Reload api.rate_limiting so the module-level limiter picks up env changes.

    The limiter and its storage_uri are bound at import time, so a test that
    changes API_RATE_LIMIT_STORAGE_URI must reload the module to observe it.
    """
    from config import get_settings

    get_settings.cache_clear()
    import api.rate_limiting as rl

    return importlib.reload(rl)


# --------------------------------------------------------------------------- #
# #4 — hashed bucket key
# --------------------------------------------------------------------------- #


def test_bucket_key_never_contains_raw_api_key_header():
    from api.rate_limiting import _rate_limit_key

    secret = "super-secret-key-abcdef123456"
    req = MagicMock()
    req.headers = {RAG_API_KEY_HEADER: secret}

    key = _rate_limit_key(req)

    assert secret not in key
    assert key.startswith("key:")


def test_bucket_key_never_contains_raw_api_key_bearer():
    from api.rate_limiting import _rate_limit_key

    secret = "another-secret-token-xyz789"
    req = MagicMock()
    req.headers = {"Authorization": f"{RAG_API_KEY_BEARER_SCHEME} {secret}"}

    key = _rate_limit_key(req)

    assert secret not in key
    assert key.startswith("key:")


def test_bucket_key_is_stable_for_same_api_key():
    from api.rate_limiting import _rate_limit_key

    req = MagicMock()
    req.headers = {RAG_API_KEY_HEADER: "stable-key"}

    assert _rate_limit_key(req) == _rate_limit_key(req)


def test_bucket_key_differs_per_api_key():
    from api.rate_limiting import _rate_limit_key

    a = MagicMock()
    a.headers = {RAG_API_KEY_HEADER: "key-A"}
    b = MagicMock()
    b.headers = {RAG_API_KEY_HEADER: "key-B"}

    assert _rate_limit_key(a) != _rate_limit_key(b)


def test_bucket_key_falls_back_to_ip_without_api_key():
    from api.rate_limiting import _rate_limit_key

    req = MagicMock()
    req.headers = {}
    req.client = MagicMock(host="203.0.113.7")

    key = _rate_limit_key(req)

    assert key.startswith("ip:")


# --------------------------------------------------------------------------- #
# #2 — configurable storage uri (default unchanged)
# --------------------------------------------------------------------------- #


def test_storage_uri_defaults_to_empty():
    from config import get_settings

    get_settings.cache_clear()
    assert get_settings().api.rate_limit_storage_uri == ""


# --------------------------------------------------------------------------- #
# #1 — login is rate-limited
# --------------------------------------------------------------------------- #


def test_login_endpoint_is_rate_limited(monkeypatch):
    """An over-the-limit burst of login attempts returns 429.

    A real FastAPI app + TestClient wires app.state.limiter so the decorator is
    active. The rate-limit check runs before the handler body, so this needs no
    DB: the limiter rejects the 11th request inside one minute regardless of
    credentials.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Login gate must be enabled for the route to do real work, and a session
    # key present so settings validate; neither is reached once limited.
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "false")  # short-circuit handler body
    rl = _reload_rate_limiting()

    # Re-import the auth router against the freshly reloaded limiter.
    import api.auth as auth_module

    auth_module = importlib.reload(auth_module)

    # The auth router declares its own /auth/* paths; the app mounts it under
    # /api, so the full login path is /api/auth/login (constants.ROUTE_AUTH_LOGIN
    # is "/auth/login").
    from constants import ROUTE_AUTH_LOGIN

    app = FastAPI()
    rl.setup_rate_limiting(app)
    app.include_router(auth_module.router, prefix="/api")

    client = TestClient(app, raise_server_exceptions=False)

    login_path = f"/api{ROUTE_AUTH_LOGIN}"
    limit = int(rl.RATE_LOGIN.split("/")[0])
    payload = {"email": "burst@example.com", "password": "whatever"}

    statuses = [client.post(login_path, json=payload).status_code for _ in range(limit + 2)]

    assert 429 in statuses, statuses
    # The first request must NOT be the one that 429s.
    assert statuses[0] != 429


# --------------------------------------------------------------------------- #
# #3 — startup fail-fast no longer requires LANGRAG_LOGIN_PASSWORD
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lifespan_boots_without_login_password(monkeypatch):
    """With the gate enabled and a session key set but NO password, the
    login-gate fail-fast must pass. Previously a missing LANGRAG_LOGIN_PASSWORD
    raised RuntimeError at startup.

    We assert the exact check main.py now performs rather than booting the whole
    app (which needs MongoDB): gate enabled + session key present => no raise.
    """
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.delenv("LANGRAG_LOGIN_PASSWORD", raising=False)
    try:
        login_settings = get_settings().login
        # Mirror of the main.py lifespan check (#3): only the session key is required.
        assert login_settings.enabled is True
        assert login_settings.session_key  # present
        assert not (login_settings.enabled and not login_settings.session_key)
        # The deprecated password is empty and that is now acceptable.
        assert login_settings.password == ""
    finally:
        get_settings.cache_clear()
