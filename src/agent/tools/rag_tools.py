"""RAG tools — thin wrappers over `src/rag/mcp/tools.py`.

The agent invokes the same retrieval + generation paths as the public
MCP server, but routed in-process so the agent runtime doesn't pay an
extra RPC hop. No ACL gating is needed: the RAG corpus (podcasts +
newsletters) is shared across all users — there is no per-community
scoping yet at the chunk level.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)


def build_rag_tools() -> list[BaseTool]:
    """Return the three RAG tools.

    The implementations delegate to `src.rag.mcp.tools.{rag_query,
    rag_search, list_rag_sources}` so the agent and the MCP surface
    stay in lockstep. Each LangChain `@tool` here just forwards args.
    """

    @tool
    async def rag_query(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
        communities: list[str] | None = None,
        include_raw_messages: bool = False,
    ) -> dict[str, Any]:
        """Full RAG answer (retrieve + generate) over LangTalks podcasts + past newsletters.

        Args:
            query: Natural-language question.
            date_start: Optional inclusive YYYY-MM-DD lower bound on source dates.
                If omitted, a recent default window is applied server-side.
            date_end: Optional inclusive YYYY-MM-DD upper bound on source dates.
            sources: Optional list to restrict to e.g. ["podcast"] or
                ["newsletter"]. If omitted, both source types are searched.
            communities: Optional list of community keys (e.g. ["langtalks",
                "mcp_israel"]) to restrict the search to specific communities.
                Podcasts (not community-scoped) are excluded when this is set.
            include_raw_messages: Set true to drill from each cited newsletter
                down to the raw underlying WhatsApp messages and answer from those
                primary sources, not just the newsletter summary. Use it when the
                summary seems too thin or the user asks for exact quotes/details.
                Costs more (extra DB lookup + larger context); leave false by default.

        Returns:
            Dict with `answer`, `citations` (each carrying source dates),
            `freshness_warning`, and the resolved date bounds.
        """
        from rag.mcp.tools import rag_query as _impl

        return await _impl(query, date_start, date_end, sources, communities=communities, include_raw_messages=include_raw_messages)

    @tool
    async def rag_search(
        query: str,
        date_start: str | None = None,
        date_end: str | None = None,
        sources: list[str] | None = None,
        communities: list[str] | None = None,
        top_k: int | None = None,
        include_raw_messages: bool = False,
    ) -> dict[str, Any]:
        """Retrieval only (no LLM call). Returns reranked citations.

        Use this when the agent wants to inspect sources before deciding
        how to answer, instead of paying for the full generation step.

        `communities` optionally restricts to specific community keys (e.g.
        ["langtalks"]); podcasts are excluded when set.

        Set `include_raw_messages` true to also attach, per citation, the raw
        underlying WhatsApp messages behind that chunk (`parent_messages`).
        """
        from rag.mcp.tools import rag_search as _impl

        return await _impl(query, date_start, date_end, sources, communities=communities, top_k=top_k, include_raw_messages=include_raw_messages)

    @tool
    async def list_rag_sources() -> dict[str, Any]:
        """List the RAG-indexed sources, grouped by type, with chunk counts and date ranges.

        Useful for the agent to introspect what content is available
        before issuing a query (e.g., "what date range do the podcasts cover?").
        """
        from rag.mcp.tools import list_rag_sources as _impl

        return await _impl()

    return [rag_query, rag_search, list_rag_sources]
