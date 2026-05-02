"""
LangRAG MCP server.

Exposes three tools — rag_query, rag_search, list_rag_sources — to Claude Code
subagents and any MCP-aware client. Supports two transports:

  - stdio (default; for local dev / direct subagent registration)
  - HTTP/SSE (for the public mcp.langrag.ai endpoint, behind nginx + TLS)

Authentication: when running in HTTP mode, an opaque bearer token (RAG_MCP_API_KEY
or settings.rag.mcp_api_key) MUST be presented in the Authorization header. The
stdio transport delegates auth to the user's local Claude Code config.
"""

import argparse
import logging
import sys

from mcp.server.fastmcp import FastMCP

from config import get_settings
from rag.mcp.tools import list_rag_sources, rag_query, rag_search

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "langrag"
MCP_SERVER_INSTRUCTIONS = (
    "RAG tools for LangTalks podcasts and past newsletters. Every answer is tagged "
    "with the source date(s); pass date_start/date_end (YYYY-MM-DD) to scope retrieval "
    "to a window. Use this when you need grounded, dated context from the LangRAG corpus."
)


def build_server() -> FastMCP:
    """Construct the FastMCP server with all RAG tools registered."""
    server = FastMCP(name=MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)

    @server.tool(
        name="rag_query",
        description=(
            "Run the full RAG chain: retrieve, then generate a date-tagged answer. "
            "Pass date_start/date_end (YYYY-MM-DD) to constrain to a window. "
            "sources is an optional list filter, e.g. ['podcast'] or ['newsletter']. "
            "Returns: answer, citations (with source_date_start/end), freshness flags."
        ),
    )
    async def _rag_query_tool(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
    ) -> dict:
        return await rag_query(query=query, date_start=date_start, date_end=date_end, sources=sources)

    @server.tool(
        name="rag_search",
        description=(
            "Retrieval only — no LLM call. Returns top-K reranked chunks with source dates. "
            "Same date and source filters as rag_query. Useful when the agent wants to "
            "compose its own answer or cite raw chunks."
        ),
    )
    async def _rag_search_tool(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
        top_k: int | None = None,
    ) -> dict:
        return await rag_search(
            query=query,
            date_start=date_start,
            date_end=date_end,
            sources=sources,
            top_k=top_k,
        )

    @server.tool(
        name="list_rag_sources",
        description=(
            "List ingested sources (podcasts, newsletters) with chunk counts and the "
            "earliest/latest source dates per source. Use this to scope queries by date."
        ),
    )
    async def _list_rag_sources_tool() -> dict:
        return await list_rag_sources()

    return server


def main() -> int:
    """Entry point. Defaults to stdio transport; pass --http to run the HTTP/SSE server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="LangRAG MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Transport mode. stdio for local subagents; http for mcp.langrag.ai.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host (http transport only)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port (http transport only)")
    args = parser.parse_args()

    settings = get_settings().rag
    if args.transport == "http" and not settings.mcp_api_key:
        logger.error(
            "Refusing to start HTTP MCP transport without RAG_MCP_API_KEY configured. "
            "Set the env var or fall back to stdio for local dev."
        )
        return 2

    server = build_server()

    if args.transport == "stdio":
        logger.info("Starting LangRAG MCP server (stdio transport)")
        server.run(transport="stdio")
        return 0

    logger.info("Starting LangRAG MCP server (HTTP/SSE transport) on %s:%s", args.host, args.port)
    server.settings.host = args.host
    server.settings.port = args.port
    server.run(transport="sse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
