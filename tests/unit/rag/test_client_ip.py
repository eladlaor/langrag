"""resolve_client_ip trusted-proxy resolution tests (no Docker).

The spoofing surface: X-Forwarded-For is client-controlled, so it may only be
honored when the immediate TCP peer is an allowlisted proxy; CF-Connecting-IP
may only be honored when Cloudflare is configured as the sole authoritative
ingress (it strips a client-supplied copy).
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest
from starlette.requests import Request

from api.client_ip import UNKNOWN_CLIENT_IP, resolve_client_ip


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request(headers: dict[str, str] | None = None, peer: str | None = "10.0.0.9") -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": raw_headers,
        "client": (peer, 55555) if peer else None,
        "query_string": b"",
    }
    return Request(scope)


def test_plain_peer_no_headers():
    assert resolve_client_ip(_request()) == "10.0.0.9"


def test_no_client_tuple_degrades_to_unknown():
    assert resolve_client_ip(_request(peer=None)) == UNKNOWN_CLIENT_IP


def test_cf_header_honored_only_when_authoritative(monkeypatch):
    from config import get_settings

    req = _request(headers={"CF-Connecting-IP": "198.51.100.42"})

    # Not authoritative (default): CF header is IGNORED (spoofable).
    assert resolve_client_ip(req) == "10.0.0.9"

    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "true")
    get_settings.cache_clear()
    assert resolve_client_ip(req) == "198.51.100.42"


def test_xff_honored_only_from_trusted_peer(monkeypatch):
    from config import get_settings

    req = _request(headers={"X-Forwarded-For": "198.51.100.42, 10.0.0.9"})

    # Untrusted peer: spoofed XFF is IGNORED, peer wins.
    assert resolve_client_ip(req) == "10.0.0.9"

    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", '["10.0.0.9"]')
    get_settings.cache_clear()
    # Trusted peer: leftmost XFF entry (the original client) wins.
    assert resolve_client_ip(req) == "198.51.100.42"


def test_cf_beats_xff_when_both_configured(monkeypatch):
    from config import get_settings

    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "true")
    monkeypatch.setenv("API_TRUSTED_PROXY_IPS", '["10.0.0.9"]')
    get_settings.cache_clear()

    req = _request(headers={"CF-Connecting-IP": "203.0.113.1", "X-Forwarded-For": "198.51.100.42"})
    assert resolve_client_ip(req) == "203.0.113.1"


def test_blank_cf_header_falls_through(monkeypatch):
    from config import get_settings

    monkeypatch.setenv("API_CLOUDFLARE_AUTHORITATIVE", "true")
    get_settings.cache_clear()

    req = _request(headers={"CF-Connecting-IP": "   "})
    assert resolve_client_ip(req) == "10.0.0.9"
