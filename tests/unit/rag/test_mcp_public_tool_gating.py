"""Public/internal MCP tool-registry gating tests.

The cost + security guarantee: in public mode the server exposes EXACTLY the two
public podcast tools and rag_query (server-side generation on our key) is NEVER
registered. Internal mode keeps the full set. Runs WITHOUT Docker.
"""

from constants import (
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_LIST_RAG_SOURCES,
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_RAG_SEARCH,
    MCP_TOOL_SEARCH_PODCASTS,
)
from rag.mcp.server import build_server


async def _tool_names(public_mode: bool) -> set[str]:
    server = build_server(public_mode=public_mode)
    tools = await server.list_tools()
    return {t.name for t in tools}


class TestPublicMode:
    async def test_exactly_the_two_public_tools(self):
        names = await _tool_names(public_mode=True)
        assert names == {MCP_TOOL_SEARCH_PODCASTS, MCP_TOOL_LIST_PODCASTS}

    async def test_rag_query_never_registered(self):
        names = await _tool_names(public_mode=True)
        assert MCP_TOOL_RAG_QUERY not in names
        assert MCP_TOOL_RAG_SEARCH not in names
        assert MCP_TOOL_LIST_RAG_SOURCES not in names


class TestInternalMode:
    async def test_registers_public_and_internal_tools(self):
        names = await _tool_names(public_mode=False)
        assert {
            MCP_TOOL_SEARCH_PODCASTS,
            MCP_TOOL_LIST_PODCASTS,
            MCP_TOOL_RAG_QUERY,
            MCP_TOOL_RAG_SEARCH,
            MCP_TOOL_LIST_RAG_SOURCES,
        } <= names


class TestConfigFlagDrivesMode:
    async def test_config_flag_selects_public(self, monkeypatch):
        from config import get_settings

        monkeypatch.setattr(get_settings().rag, "mcp_public_mode", True, raising=False)
        server = build_server()  # no explicit override -> reads config
        names = {t.name for t in await server.list_tools()}
        assert names == {MCP_TOOL_SEARCH_PODCASTS, MCP_TOOL_LIST_PODCASTS}
