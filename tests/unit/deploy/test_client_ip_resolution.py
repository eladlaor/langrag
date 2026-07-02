"""Trusted-proxy client-IP resolution tests (I1) — no Docker.

The per-IP rate-limit key must resolve to the REAL client, not the proxy, and
must never honor a spoofable X-Forwarded-For from an untrusted peer.
"""

from types import SimpleNamespace

import pytest

from constants import HEADER_CF_CONNECTING_IP, HEADER_X_FORWARDED_FOR


class _FakeRequest:
    def __init__(self, *, peer, headers=None):
        self.client = SimpleNamespace(host=peer, port=0)
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client_ip(request):
    from api.rate_limiting import _client_ip as fn

    return fn(request)


def test_no_proxy_uses_peer(monkeypatch):
    # Dev/no-proxy: use the raw peer, ignore any XFF (untrusted).
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", "[]")
    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "false")
    from config import get_settings

    get_settings.cache_clear()

    req = _FakeRequest(peer="203.0.113.9", headers={HEADER_X_FORWARDED_FOR: "1.1.1.1"})
    assert _client_ip(req) == "203.0.113.9"


def test_untrusted_peer_xff_ignored(monkeypatch):
    # Peer is NOT in the allowlist -> a forged XFF must be ignored.
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", '["10.0.0.1"]')
    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "false")
    from config import get_settings

    get_settings.cache_clear()

    req = _FakeRequest(peer="203.0.113.9", headers={HEADER_X_FORWARDED_FOR: "6.6.6.6"})
    assert _client_ip(req) == "203.0.113.9"


def test_trusted_peer_uses_leftmost_xff(monkeypatch):
    # Peer IS the trusted proxy -> use the leftmost (original client) XFF entry.
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", '["10.0.0.1"]')
    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "false")
    from config import get_settings

    get_settings.cache_clear()

    req = _FakeRequest(peer="10.0.0.1", headers={HEADER_X_FORWARDED_FOR: "198.51.100.5, 10.0.0.1"})
    assert _client_ip(req) == "198.51.100.5"


def test_cloudflare_authoritative_uses_cf_header(monkeypatch):
    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "true")
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", "[]")
    from config import get_settings

    get_settings.cache_clear()

    req = _FakeRequest(peer="10.0.0.1", headers={HEADER_CF_CONNECTING_IP: "198.51.100.77", HEADER_X_FORWARDED_FOR: "6.6.6.6"})
    assert _client_ip(req) == "198.51.100.77"


def test_cloudflare_authoritative_missing_header_falls_back(monkeypatch):
    # CF authoritative but header absent -> do not invent; fall through to peer
    # (trusted-proxy allowlist empty here).
    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "true")
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", "[]")
    from config import get_settings

    get_settings.cache_clear()

    req = _FakeRequest(peer="203.0.113.9", headers={})
    assert _client_ip(req) == "203.0.113.9"
