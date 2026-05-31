"""Process-wide agent runtime singleton.

Lazily constructs the compiled `AgentGraph` + its production
collaborators on first use. Centralizing this here keeps the FastAPI
route handler tiny and gives tests a single seam for swapping the
graph / store / kickoff with stubs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool

from agent.memory.mongodb_store import MongoDBStore
from config import get_settings
from constants import COLLECTION_AGENT_MEMORIES

logger = logging.getLogger(__name__)


_runtime_lock = asyncio.Lock()
_compiled_graph: Any | None = None
_store: MongoDBStore | None = None


async def get_agent_graph() -> Any:
    """Return the process-wide compiled agent graph (build on first call)."""
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph
    async with _runtime_lock:
        if _compiled_graph is not None:
            return _compiled_graph
        _compiled_graph = await _build_runtime()
    return _compiled_graph


async def get_agent_store() -> MongoDBStore:
    """Return the process-wide `MongoDBStore` used by tools + memory nodes."""
    global _store
    if _store is not None:
        return _store
    await get_agent_graph()  # builds both
    if _store is None:
        raise RuntimeError("Agent runtime build did not produce a store")
    return _store


async def reset_agent_runtime() -> None:
    """Clear cached runtime (tests + reload paths)."""
    global _compiled_graph, _store
    async with _runtime_lock:
        _compiled_graph = None
        _store = None


async def _build_runtime() -> Any:
    """Assemble the runtime collaborators and compile the graph.

    Imports are local so this module stays cheap when AGENT_ENABLED=false.
    """
    from agent.graph import build_agent_graph
    from db.connection import get_database
    from graphs.checkpointer import get_checkpointer
    from utils.embedding.factory import EmbeddingProviderFactory

    settings = get_settings()
    db = await get_database()
    checkpointer = await get_checkpointer()

    # Embedder shared by MongoDBStore writes + retriever queries.
    rag_model = settings.rag_embedding.model or settings.embedding.default_model
    embedder = EmbeddingProviderFactory.create(model=rag_model)

    global _store
    _store = MongoDBStore(
        collection=db[COLLECTION_AGENT_MEMORIES],
        embedder=embedder,
        embedding_model=rag_model,
    )

    # Build the LLM factories. Lazy imports so this module is import-safe
    # without the anthropic dep when AGENT_ENABLED=false.
    def agent_llm_factory(tools: list[BaseTool]):
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(model=settings.agent.agent_model)
        return llm.bind_tools(tools)

    def memory_llm_factory():
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.agent.memory_model)

    # Newsletter kickoff: schedules a background task that runs the
    # existing parallel_orchestrator_graph. The orchestrator is the same
    # one /api/generate_periodic_newsletter calls; we just invoke it as
    # a fire-and-forget so the tool returns immediately with run_id.
    async def kickoff_fn(params: dict[str, Any], ctx) -> str:
        from api.newsletter_gen import build_orchestrator_state, setup_output_directory
        from custom_types.api_schemas import PeriodicNewsletterRequest
        from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph

        # Translate the tool's flat dict into the full request schema. We
        # default the chats list to "all chats in the community" when not
        # provided; the API layer does the same when whatsapp_chat_names is
        # empty.
        from constants import KNOWN_WHATSAPP_CHAT_NAMES

        chats = params.get("chats") or KNOWN_WHATSAPP_CHAT_NAMES.get(
            params["community"], []
        )
        req = PeriodicNewsletterRequest(
            data_source_name=params["community"],
            whatsapp_chat_names_to_include=list(chats),
            start_date=params["start_date"],
            end_date=params["end_date"],
            desired_language_for_summary=params.get("desired_language", "english"),
            summary_format=params.get("summary_format", "langtalks_format"),
            consolidate_chats=params.get("consolidate_chats", True),
        )

        run_dir = setup_output_directory(req)
        # The orchestrator state expects a thread_id; reuse run_dir's basename
        # so logs can correlate the agent-kicked run with the pipeline.
        import os

        thread_id = os.path.basename(run_dir)
        state = build_orchestrator_state(req, run_dir, thread_id)
        run_id = state.get("run_id") or thread_id

        graph = await get_parallel_orchestrator_graph()
        # Fire-and-forget; the agent's get_run_status / get_newsletter
        # tools surface progress.
        asyncio.create_task(_run_orchestrator(graph, state, thread_id))
        logger.info(
            "agent kickoff_fn: user_id=%s community=%s run_id=%s",
            ctx.user_id,
            params["community"],
            run_id,
        )
        return run_id

    graph = await build_agent_graph(
        checkpointer=checkpointer,
        store=_store,
        kickoff_fn=kickoff_fn,
        agent_llm_factory=agent_llm_factory,
        memory_llm_factory=memory_llm_factory,
    )
    return graph


async def _run_orchestrator(graph, state, thread_id: str) -> None:
    """Background runner for an agent-kicked newsletter pipeline."""
    try:
        await graph.ainvoke(state, config={"configurable": {"thread_id": thread_id}})
    except Exception as e:  # pragma: no cover
        logger.exception("Agent-kicked orchestrator run %s failed: %s", thread_id, e)
