"""Regression tests for the MCP HTTP/SSE transport DNS-rebinding guard.

v1.20.0 shipped build_server() without setting transport_security, so the MCP
SDK's default localhost-only allowed_hosts rejected a request forwarded by
nginx/Cloudflare with `Host: mcp.langrag.ai` (HTTP 421 after auth). These tests
pin the config-driven behaviour that fixes it.
"""

import importlib

import pytest

import config as config_module
from rag.mcp.server import build_server


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Each test drives config via env, so drop the cached Settings first/after."""
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def test_empty_allowlist_disables_rebinding_guard(monkeypatch):
    """No configured hosts => guard OFF (nginx is the sole ingress and pins vhost)."""
    monkeypatch.setenv("RAG_MCP_ALLOWED_HOSTS", "")
    config_module.get_settings.cache_clear()

    server = build_server(public_mode=True)
    ts = server.settings.transport_security

    assert ts is not None
    assert ts.enable_dns_rebinding_protection is False


def test_configured_host_is_allowlisted(monkeypatch):
    """A configured public host is allowlisted so Host: mcp.langrag.ai is accepted."""
    monkeypatch.setenv("RAG_MCP_ALLOWED_HOSTS", "mcp.langrag.ai")
    config_module.get_settings.cache_clear()

    server = build_server(public_mode=True)
    ts = server.settings.transport_security

    assert ts.enable_dns_rebinding_protection is True
    assert ts.allowed_hosts == ["mcp.langrag.ai"]
    assert ts.allowed_origins == ["https://mcp.langrag.ai"]


def test_multiple_hosts_comma_separated(monkeypatch):
    """Comma-separated hosts are each allowlisted with a matching https origin."""
    monkeypatch.setenv("RAG_MCP_ALLOWED_HOSTS", "mcp.langrag.ai, mcp2.langrag.ai")
    config_module.get_settings.cache_clear()

    server = build_server(public_mode=True)
    ts = server.settings.transport_security

    assert ts.allowed_hosts == ["mcp.langrag.ai", "mcp2.langrag.ai"]
    assert ts.allowed_origins == ["https://mcp.langrag.ai", "https://mcp2.langrag.ai"]
