"""
LangRAG MCP server.

Two tool surfaces, selected by RAG_MCP_PUBLIC_MODE (settings.rag.mcp_public_mode):

  - PUBLIC mode (public multi-podcast platform): registers ONLY the frozen public
    tools — search_podcasts, list_podcasts. rag_query (server-side generation on
    our OpenAI key) and the internal rag_search / list_rag_sources are NEVER
    registered, so they are unreachable regardless of routing.
  - INTERNAL mode (default): registers the internal tools — rag_query, rag_search,
    list_rag_sources — for local subagents and internal deployments, preserving
    current behavior. The public tools are also registered so internal callers can
    exercise the public contract.

Supported transports:
  - stdio (default; for local dev / direct subagent registration)
  - Streamable HTTP (for the public mcp.langrag.ai endpoint, behind nginx + TLS;
    clients connect to the /mcp endpoint, stateless mode — no session tracking)

Authentication: when running in HTTP mode, an opaque bearer token (RAG_MCP_API_KEY
or settings.rag.mcp_api_key) MUST be presented in the Authorization header. The
stdio transport delegates auth to the user's local Claude Code config.
"""

import argparse
import logging
import sys
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from config import get_settings
from constants import (
    MCP_SESSION_ID_PREFIX,
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_LIST_RAG_SOURCES,
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_RAG_SEARCH,
    MCP_TOOL_SEARCH_PODCASTS,
    MCP_TRACE_USER,
)
from rag.mcp.auth_context import (
    ConsumerKeyAuthMiddleware,
    authorize_current_tool,
    mark_http_transport_active,
    touch_current_consumer_last_used,
)
from rag.mcp.tools import list_podcasts, list_rag_sources, rag_query, rag_search, search_podcasts

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "langrag"
MCP_SERVER_INSTRUCTIONS = "RAG tools for querying podcasts (and, on internal deployments, past newsletters). Every result is tagged with the source date(s); pass date_start/date_end (YYYY-MM-DD) to scope retrieval to a window. Call list_podcasts to discover which shows are queryable, then search_podcasts to retrieve dated, cited chunks and compose your own answer."


def _new_session_id() -> str:
    # FastMCP carries no caller identity, so each tool call becomes its own
    # grouped Langfuse trace via a synthesized per-call session id.
    return f"{MCP_SESSION_ID_PREFIX}{uuid.uuid4().hex[:8]}"


def _register_public_tools(server: FastMCP) -> None:
    """Register the frozen public multi-podcast tools (search-only, $0 generation)."""

    @server.tool(
        name=MCP_TOOL_SEARCH_PODCASTS,
        description=("Search the podcast corpus. Returns top-K reranked chunks with source dates (no LLM call — your agent composes the answer). `podcast` is an optional slug filter (from list_podcasts); omit it to search all podcasts. Pass date_start/date_end (YYYY-MM-DD) to scope to a window."),
    )
    async def _search_podcasts_tool(
        query: str,
        podcast: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        top_k: int | None = None,
    ) -> dict:
        # Server-side scope gate: even a public tool is authorized against the
        # presented key (no-op on stdio, where no key record is set).
        await authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)
        # Concurrency admission control is enforced transitively inside tools.rag_search.
        result = await search_podcasts(
            query=query,
            podcast=podcast,
            date_start=date_start,
            date_end=date_end,
            top_k=top_k,
            session_id=_new_session_id(),
            user_id=MCP_TRACE_USER,
        )
        touch_current_consumer_last_used()
        return result

    @server.tool(
        name=MCP_TOOL_LIST_PODCASTS,
        description=("List the podcasts available to query, with per-podcast chunk counts and the earliest/latest source dates. Use this to discover slugs for the `podcast` filter and to scope queries by date."),
    )
    async def _list_podcasts_tool() -> dict:
        await authorize_current_tool(MCP_TOOL_LIST_PODCASTS)
        result = await list_podcasts()
        touch_current_consumer_last_used()
        return result


def _register_internal_tools(server: FastMCP) -> None:
    """Register the internal tools (rag_query does server-side generation on OUR key)."""

    @server.tool(
        name=MCP_TOOL_RAG_QUERY,
        description=("Run the full RAG chain: retrieve, then generate a date-tagged answer. Pass date_start/date_end (YYYY-MM-DD) to constrain to a window. sources is an optional list filter, e.g. ['podcast'] or ['newsletter']. Returns: answer, citations (with source_date_start/end), freshness flags."),
    )
    async def _rag_query_tool(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
    ) -> dict:
        # A PODCAST_QUERY-scoped key must be rejected here even in internal mode.
        await authorize_current_tool(MCP_TOOL_RAG_QUERY)
        return await rag_query(
            query=query,
            date_start=date_start,
            date_end=date_end,
            sources=sources,
            session_id=_new_session_id(),
            user_id=MCP_TRACE_USER,
        )

    @server.tool(
        name=MCP_TOOL_RAG_SEARCH,
        description=("Retrieval only — no LLM call. Returns top-K reranked chunks with source dates. Same date and source filters as rag_query. Useful when the agent wants to compose its own answer or cite raw chunks."),
    )
    async def _rag_search_tool(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
        top_k: int | None = None,
    ) -> dict:
        await authorize_current_tool(MCP_TOOL_RAG_SEARCH)
        return await rag_search(
            query=query,
            date_start=date_start,
            date_end=date_end,
            sources=sources,
            top_k=top_k,
            session_id=_new_session_id(),
            user_id=MCP_TRACE_USER,
        )

    @server.tool(
        name=MCP_TOOL_LIST_RAG_SOURCES,
        description=("List ingested sources (podcasts, newsletters) with chunk counts and the earliest/latest source dates per source. Use this to scope queries by date."),
    )
    async def _list_rag_sources_tool() -> dict:
        await authorize_current_tool(MCP_TOOL_LIST_RAG_SOURCES)
        return await list_rag_sources()


def build_server(public_mode: bool | None = None) -> FastMCP:
    """Construct the FastMCP server with the tool set for the active mode.

    Args:
        public_mode: Override the configured mode (settings.rag.mcp_public_mode).
            When None, the config flag is read. In public mode ONLY the public
            podcast tools are registered; rag_query is never reachable.
    """
    rag_settings = get_settings().rag
    if public_mode is None:
        public_mode = rag_settings.mcp_public_mode

    server = FastMCP(name=MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)

    # DNS-rebinding guard for the Streamable HTTP transport. The MCP SDK defaults its
    # allowed_hosts to localhost-only, so a request forwarded by nginx/Cloudflare
    # with Host: mcp.langrag.ai is rejected with HTTP 421 AFTER auth passes,
    # blocking every external client. We drive it from config: a non-empty
    # mcp_allowed_hosts allowlists those hosts; an empty value disables the guard
    # entirely, which is safe here because nginx is the sole ingress and pins the
    # vhost to this upstream. Harmless for the stdio transport (never consulted).
    allowed_hosts_raw = rag_settings.mcp_allowed_hosts.strip()
    if allowed_hosts_raw:
        hosts = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]
        origins = [f"https://{h}" for h in hosts]
        server.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )
        logger.info("MCP transport DNS-rebinding guard: allowlisting hosts %s", hosts)
    else:
        server.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        logger.info("MCP transport DNS-rebinding guard disabled (nginx is sole ingress)")

    # Public tools are always available. In public mode they are the ENTIRE
    # surface; the internal tools (esp. rag_query's server-side generation) are
    # never registered, so they cannot be invoked regardless of routing.
    _register_public_tools(server)
    if public_mode:
        logger.info("MCP server built in PUBLIC mode: only search_podcasts + list_podcasts registered")
    else:
        _register_internal_tools(server)
        logger.info("MCP server built in INTERNAL mode: public + internal tools registered")

    return server


def main() -> int:
    """Entry point. Defaults to stdio transport; pass --transport http to run the Streamable HTTP server."""
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
        help="Transport mode. stdio for local subagents; http (Streamable HTTP) for mcp.langrag.ai.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host (http transport only)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port (http transport only)")
    args = parser.parse_args()

    settings = get_settings().rag
    if args.transport == "http" and not settings.mcp_api_key:
        logger.error("Refusing to start HTTP MCP transport without RAG_MCP_API_KEY configured. Set the env var or fall back to stdio for local dev.")
        return 2

    server = build_server()

    if args.transport == "stdio":
        logger.info("Starting LangRAG MCP server (stdio transport)")
        server.run(transport="stdio")
        return 0

    # Loud fail-fast alarm if the HTTP transport starts with the internal tools
    # exposed behind mere bearer auth (public mode OFF). A misconfigured prod
    # would otherwise silently serve rag_query (server-side generation on OUR
    # key) to anyone holding a bearer. Scope enforcement still gates per-key, but
    # a prod HTTP deployment should almost always be public mode.
    if not settings.mcp_public_mode:
        logger.warning(
            "HTTP MCP transport starting with mcp_public_mode=False: internal tools (rag_query/rag_search/list_rag_sources) are REGISTERED and exposed behind bearer auth only. Set RAG_MCP_PUBLIC_MODE=true for the public endpoint.",
            extra={"event": "mcp_http_internal_tools_exposed"},
        )

    # COST-5: pin the MCP process to its own, lower concurrency cap (SEPARATE from
    # the REST app's max_concurrent_requests) so the shared 4GB box is not driven
    # to ~50 concurrent retrievals by the MCP surface alone. Set BEFORE the first
    # acquire, in the standalone :8765 process only.
    from rag.concurrency.guard import configure_cap

    configure_cap(settings.mcp_max_concurrent)
    logger.info("MCP process concurrency cap pinned", extra={"cap": settings.mcp_max_concurrent})

    logger.info("Starting LangRAG MCP server (Streamable HTTP transport) on %s:%s", args.host, args.port)
    _run_streamable_http_with_auth(server, host=args.host, port=args.port)
    return 0


def _run_streamable_http_with_auth(server: FastMCP, *, host: str, port: int) -> None:
    """Run the Streamable HTTP transport with the consumer-key auth middleware attached.

    FastMCP's `run(transport="streamable-http")` builds the Starlette app
    internally with no hook to add middleware, so we build the app ourselves,
    wrap it with ConsumerKeyAuthMiddleware (which authenticates the bearer and
    sets the per-request key-record context the tool wrappers enforce scope
    against), and serve it with uvicorn. The app's own lifespan runs the
    StreamableHTTPSessionManager, so uvicorn's lifespan handling covers it.

    Stateless mode: each POST /mcp is authenticated and served independently,
    with no server-side session tracking. This matches our synthesized per-call
    Langfuse session ids and means the auth context is set fresh on the exact
    request whose tool call it authorizes (no cross-request context propagation
    to reason about, unlike the retired SSE transport's GET/POST split).

    Flags the HTTP transport active so the scope gate fails CLOSED: a tool call
    that reaches execution with no resolvable key record is rejected, never
    silently allowed.
    """
    import uvicorn

    mark_http_transport_active()

    server.settings.stateless_http = True
    starlette_app = server.streamable_http_app()
    starlette_app.add_middleware(ConsumerKeyAuthMiddleware)

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    uvicorn.Server(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
