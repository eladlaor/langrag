"""Deployment-invariant unit tests for MCP + production Langfuse enablement.

All tests here are pure-parse / pure-import (no Docker, no network). They pin the
committed compose/nginx/env/Dockerfile files to the contract described in
knowledge/plans/RAG_MCP_AND_LANGFUSE_DEPLOY_ENABLEMENT.md so the confirmed
nginx-upstream bug, the production profile gating, the MCP edge caps, the
remote-Langfuse override, and the single-uvicorn-worker rule cannot regress.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

NGINX_HTTPS = REPO_ROOT / "nginx-https.conf"
NGINX_MAIN = REPO_ROOT / "nginx.conf"
COMPOSE = REPO_ROOT / "docker-compose.yml"
COMPOSE_LANGFUSE_REMOTE = REPO_ROOT / "docker-compose.langfuse-remote.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
RATE_LIMITING = REPO_ROOT / "src" / "api" / "rate_limiting.py"

MCP_SERVICE_NAME = "mcp-server"
MCP_UPSTREAM = "http://langrag-mcp:8765"
MCP_LOCALHOST_UPSTREAM = "http://localhost:8765"
PRODUCTION_PROFILE = "production"
PARKED_PROFILE = "never"
MCP_CONN_ZONE = "mcp_conn"
MCP_REQ_ZONE = "mcp_req"
MCP_RATE = "30r/m"
REST_RATE_DEFAULT = "30/minute"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file missing: {path}"
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(_read(path))


def _mcp_server_block(text: str) -> str:
    """Return the text of the `server { ... server_name mcp.langrag.ai ... }` block."""
    idx = text.index("server_name mcp.langrag.ai")
    # Walk back to the enclosing `server {` and forward to its matching close brace.
    start = text.rindex("server {", 0, idx)
    depth = 0
    i = text.index("{", start)
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    raise AssertionError("unterminated mcp.langrag.ai server block in nginx-https.conf")


def test_mcp_nginx_upstream_targets_service_dns_not_localhost():
    block = _mcp_server_block(_read(NGINX_HTTPS))
    assert f"proxy_pass {MCP_UPSTREAM};" in block, "MCP nginx upstream must target the langrag-mcp service DNS name"
    assert f"proxy_pass {MCP_LOCALHOST_UPSTREAM}" not in block, "MCP nginx upstream must NOT be localhost:8765 (nginx and MCP are in different containers)"


def test_mcp_service_is_production_profiled():
    services = _load_yaml(COMPOSE)["services"]
    assert services[MCP_SERVICE_NAME]["profiles"] == [PRODUCTION_PROFILE], "mcp-server must be gated behind the production profile so it never auto-starts in dev"


def test_mcp_service_requires_api_key_fail_fast():
    env = _load_yaml(COMPOSE)["services"][MCP_SERVICE_NAME]["environment"]
    joined = "\n".join(f"{k}={v}" for k, v in env.items()) if isinstance(env, dict) else "\n".join(env)
    assert "RAG_MCP_API_KEY:?" in joined, "mcp-server RAG_MCP_API_KEY must use the compose-parse-time fail-fast (:?) form"


def test_mcp_server_refuses_http_without_api_key(monkeypatch):
    import config
    from rag.mcp import server

    class _Rag:
        mcp_api_key = ""

    class _Settings:
        rag = _Rag()

    monkeypatch.setattr(server, "get_settings", lambda: _Settings())
    monkeypatch.setattr(config, "get_settings", lambda: _Settings(), raising=False)
    monkeypatch.setattr("sys.argv", ["prog", "--transport", "http"])

    assert server.main() == 2, "MCP server must refuse to start HTTP transport (return 2) without RAG_MCP_API_KEY"


def test_nginx_defines_mcp_limit_zones():
    main_text = _read(NGINX_MAIN)
    https_text = _read(NGINX_HTTPS)

    assert re.search(rf"limit_conn_zone\s+\S+\s+zone={MCP_CONN_ZONE}:", main_text), "nginx.conf must declare the mcp_conn limit_conn_zone in http{}"
    assert re.search(rf"limit_req_zone\s+.*zone={MCP_REQ_ZONE}:", main_text), "nginx.conf must declare the mcp_req limit_req_zone in http{}"

    block = _mcp_server_block(https_text)
    assert re.search(rf"limit_conn\s+{MCP_CONN_ZONE}\s", block), "mcp.langrag.ai block must reference limit_conn mcp_conn"
    assert re.search(rf"limit_req\s+zone={MCP_REQ_ZONE}", block), "mcp.langrag.ai block must reference limit_req zone=mcp_req"


def test_mcp_rate_matches_rest_default():
    main_text = _read(NGINX_MAIN)
    m = re.search(rf"limit_req_zone\s+.*zone={MCP_REQ_ZONE}:\S+\s+rate=(\S+);", main_text)
    assert m, "mcp_req limit_req_zone must declare a rate="
    assert m.group(1) == MCP_RATE, f"mcp_req rate must be {MCP_RATE}"

    rate_text = _read(RATE_LIMITING)
    assert f'RATE_DEFAULT = "{REST_RATE_DEFAULT}"' in rate_text, "RATE_DEFAULT in rate_limiting.py must stay 30/minute"
    # 30r/m (nginx) == 30/minute (slowapi): one documented number.
    assert MCP_RATE.rstrip("r/m") == REST_RATE_DEFAULT.split("/")[0], "MCP edge rate and REST default must be the same number"


def test_langfuse_remote_override_parks_local_stack():
    services = _load_yaml(COMPOSE_LANGFUSE_REMOTE)["services"]
    assert services["langfuse-server"]["profiles"] == [PARKED_PROFILE], "override must park langfuse-server under the never profile"
    assert services["langfuse-db"]["profiles"] == [PARKED_PROFILE], "override must park langfuse-db under the never profile"

    for svc in ("app", MCP_SERVICE_NAME):
        env = services[svc]["environment"]
        joined = "\n".join(f"{k}={v}" for k, v in env.items()) if isinstance(env, dict) else "\n".join(env)
        assert "LANGFUSE_HOST" in joined, f"{svc} must set LANGFUSE_HOST in the remote override"
        assert "LANGFUSE_HOST:?" in joined or "LANGFUSE_HOST:?" in joined.replace("${", "").replace("}", ""), f"{svc} LANGFUSE_HOST must be a required (:?) env var in the remote override"


def test_dockerfile_single_uvicorn_worker():
    text = _read(DOCKERFILE)
    assert "uvicorn" in text, "Dockerfile must launch uvicorn"
    assert "--workers" not in text, "Dockerfile uvicorn CMD must not set --workers (>1 breaks the in-memory slowapi limiter)"
