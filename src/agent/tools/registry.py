"""Assemble the per-session tool registry.

The agent graph builds one tool list per session at compile time. The
list is a closure over:
  - the per-user `MongoDBStore` (for memory tools)
  - the production-newsletter kickoff callable (for `generate_newsletter`)

These are passed via `build_tools_for_session(...)` rather than being
read from the active `UserContext` directly, so a single agent process
can serve many concurrent sessions without leaking state across them.
The tools still read the live `UserContext` from the contextvar — but
that's read-only per-turn data, not session-scoped infrastructure.
"""

from __future__ import annotations


from langchain_core.tools import BaseTool

from agent.memory.mongodb_store import MongoDBStore

from .community_tools import build_community_tools
from .memory_tools import build_memory_tools
from .newsletter_tools import KickoffFn, build_newsletter_tools
from .rag_tools import build_rag_tools
from .schedule_tools import build_schedule_tools

__all__ = ["build_tools_for_session", "KickoffFn"]


def build_tools_for_session(
    store: MongoDBStore,
    kickoff_fn: KickoffFn,
) -> list[BaseTool]:
    """Return all agent tools, wired for one session.

    Tool order is deterministic so the LLM's tool-selection prompt sees
    a stable list. Order: RAG → community → memory → newsletter → schedule.
    """
    tools: list[BaseTool] = []
    tools.extend(build_rag_tools())
    tools.extend(build_community_tools())
    tools.extend(build_memory_tools(store_factory=lambda: store))
    tools.extend(build_newsletter_tools(kickoff_fn=kickoff_fn))
    tools.extend(build_schedule_tools())
    return tools
