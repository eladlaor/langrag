"""Newsletter tools.

Wraps the existing newsletter pipeline so the agent can:
  - kick off a newsletter generation (returns a `run_id`)
  - poll its status
  - list past runs (scoped to communities the user owns)
  - fetch a finished newsletter's content

All write operations (`generate_newsletter`) are ACL-gated: the user
must own the requested community.

`generate_newsletter` itself is implemented in terms of a `kickoff_fn`
the registry binds at build time. The production agent runtime (commit 7)
wires the real `parallel_orchestrator_graph` kickoff there; unit tests
inject a stub. This keeps this commit independent of the full newsletter
graph wiring while preserving the public contract.
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from agent.auth.acl import assert_user_owns_community
from agent.auth.user_context import current_user_context
from custom_types.field_keys import DbFieldKeys
from db.connection import get_database
from db.repositories.newsletters import NewslettersRepository
from db.repositories.runs import RunsRepository

logger = logging.getLogger(__name__)


# A kickoff_fn takes structured newsletter params + the user's UserContext
# and returns a freshly-created run_id. The runtime injects a function
# that schedules the orchestrator graph as a background task; tests
# inject a deterministic stub.
KickoffFn = Callable[[dict[str, Any], Any], Awaitable[str]]


def build_newsletter_tools(kickoff_fn: KickoffFn) -> list[BaseTool]:
    """Construct the four newsletter tools.

    Args:
        kickoff_fn: Async callable invoked by `generate_newsletter` to
            start the pipeline. Receives `(params_dict, user_context)`
            and returns the new `run_id`.
    """

    @tool
    async def generate_newsletter(
        community: str,
        start_date: str,
        end_date: str,
        chats: list[str] | None = None,
        desired_language: str = "english",
        summary_format: str = "langtalks_format",
        consolidate_chats: bool = True,
        send_email: bool = False,
    ) -> dict[str, Any]:
        """Kick off a newsletter generation for one community / date window.

        Returns a `run_id` synchronously. The pipeline runs in the
        background; use `get_run_status` to poll, and `get_newsletter`
        to fetch the output once `status == "completed"`.

        Args:
            community: Community key (one of the keys returned by
                `list_my_communities`).
            start_date: YYYY-MM-DD inclusive.
            end_date: YYYY-MM-DD inclusive.
            chats: Optional restriction to specific chat names within
                the community. If omitted, all community chats are used.
            desired_language: Output language (e.g., "english", "hebrew").
            summary_format: One of "langtalks_format", "mcp_israel_format".
            consolidate_chats: When True, produce one consolidated
                newsletter across the chats; when False, one per chat.
            send_email: When True, the pipeline will email the result to
                the user's configured recipients. The route handler
                attaches an `interrupt()` for confirmation when this is
                set, per commit 10.

        Returns:
            Dict with `run_id` and a short human-readable description.
        """
        ctx = current_user_context()
        assert_user_owns_community(ctx, community)

        # HITL gate: send_email is the destructive variant (a real
        # email goes out to recipients). Non-send_email runs only
        # produce on-disk artifacts that the user can inspect before
        # deciding what to do, so they don't need the confirm step.
        if send_email:
            decision = interrupt(
                {
                    "kind": "confirm",
                    "action": "generate_newsletter_and_email",
                    "args": {
                        "community": community,
                        "start_date": start_date,
                        "end_date": end_date,
                        "desired_language": desired_language,
                    },
                }
            )
            if str(decision).lower() != "approve":
                logger.info(
                    "generate_newsletter+email: user_id=%s community=%s rejected by user",
                    ctx.user_id,
                    community,
                )
                return {
                    "run_id": None,
                    "description": (
                        "Newsletter generation was rejected by the user; "
                        "no run was started."
                    ),
                    "reason": "rejected_by_user",
                }

        params: dict[str, Any] = {
            "community": community,
            "start_date": start_date,
            "end_date": end_date,
            "chats": chats,
            "desired_language": desired_language,
            "summary_format": summary_format,
            "consolidate_chats": consolidate_chats,
            "send_email": bool(send_email),
        }
        run_id = await kickoff_fn(params, ctx)
        logger.info(
            "generate_newsletter: user_id=%s community=%s run_id=%s",
            ctx.user_id,
            community,
            run_id,
        )
        return {
            "run_id": run_id,
            "description": (
                f"Newsletter generation started for {community} "
                f"({start_date} → {end_date})."
            ),
        }

    @tool
    async def get_run_status(run_id: str) -> dict[str, Any]:
        """Return the current status of a newsletter run.

        The current user must own the run's `data_source_name`
        (community); cross-tenant status leakage is refused.

        Args:
            run_id: The id returned by `generate_newsletter`.

        Returns:
            Dict with `run_id`, `status`, `data_source_name`,
            `created_at`, and the most recent `stages` blob.
        """
        ctx = current_user_context()
        db = await get_database()
        repo = RunsRepository(db)
        row = await repo.get_run(run_id)
        if row is None:
            return {"run_id": run_id, "status": "not_found"}

        ds = row.get(DbFieldKeys.DATA_SOURCE_NAME, "")
        if ds and not ctx.owns(ds):
            # Don't even reveal that the run exists.
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": row.get("run_id"),
            "status": row.get(DbFieldKeys.STATUS),
            "data_source_name": ds,
            "start_date": row.get(DbFieldKeys.START_DATE),
            "end_date": row.get(DbFieldKeys.END_DATE),
            "created_at": _stringify_dt(row.get(DbFieldKeys.CREATED_AT)),
            "completed_at": _stringify_dt(row.get(DbFieldKeys.COMPLETED_AT)),
            "stages": row.get("stages", {}),
            "error": row.get("error"),
        }

    @tool
    async def list_recent_runs(
        community: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List recent newsletter runs scoped to communities the user owns.

        Args:
            community: Optional filter to a single community key (must
                be one the user owns; an unowned key returns empty).
            limit: Max results.

        Returns:
            List of run summaries newest first. Each carries `run_id`,
            `status`, `data_source_name`, `start_date`, `end_date`.
        """
        ctx = current_user_context()
        db = await get_database()
        repo = RunsRepository(db)

        if community is not None and not ctx.owns(community):
            return []

        # The repo's get_recent_runs filters by data_source_name when
        # provided. We always post-filter to keep us inside owned
        # communities (cheap; runs come back sorted).
        raw = await repo.get_recent_runs(limit=limit * 3, data_source_name=community)
        out: list[dict[str, Any]] = []
        for row in raw:
            ds = row.get(DbFieldKeys.DATA_SOURCE_NAME, "")
            if ds and not ctx.owns(ds):
                continue
            out.append(
                {
                    "run_id": row.get("run_id"),
                    "status": row.get(DbFieldKeys.STATUS),
                    "data_source_name": ds,
                    "start_date": row.get(DbFieldKeys.START_DATE),
                    "end_date": row.get(DbFieldKeys.END_DATE),
                    "created_at": _stringify_dt(row.get(DbFieldKeys.CREATED_AT)),
                }
            )
            if len(out) >= limit:
                break
        return out

    @tool
    async def get_newsletter(run_id: str) -> dict[str, Any]:
        """Fetch the rendered newsletter(s) for a completed run.

        Args:
            run_id: The id returned by `generate_newsletter`.

        Returns:
            Dict with `run_id` and a list of `newsletters` (one per chat
            for non-consolidated runs; one item for consolidated).
            Each newsletter carries `newsletter_id`, `newsletter_type`,
            `chat_name`, `summary_format`, `desired_language`, and
            `markdown_content` (when available).
        """
        ctx = current_user_context()
        db = await get_database()
        runs_repo = RunsRepository(db)
        nl_repo = NewslettersRepository(db)

        run_row = await runs_repo.get_run(run_id)
        if run_row is None:
            return {"run_id": run_id, "status": "not_found", "newsletters": []}
        ds = run_row.get(DbFieldKeys.DATA_SOURCE_NAME, "")
        if ds and not ctx.owns(ds):
            return {"run_id": run_id, "status": "not_found", "newsletters": []}

        newsletters_raw = await nl_repo.get_newsletters_by_run(run_id)
        items: list[dict[str, Any]] = []
        for nl in newsletters_raw:
            markdown = await nl_repo.get_newsletter_content(
                nl["newsletter_id"], version="original", format="markdown"
            )
            items.append(
                {
                    "newsletter_id": nl.get("newsletter_id"),
                    "newsletter_type": nl.get(DbFieldKeys.NEWSLETTER_TYPE),
                    "chat_name": nl.get(DbFieldKeys.CHAT_NAME),
                    "summary_format": nl.get(DbFieldKeys.SUMMARY_FORMAT),
                    "desired_language": nl.get(DbFieldKeys.DESIRED_LANGUAGE),
                    "markdown_content": markdown,
                }
            )
        return {"run_id": run_id, "status": run_row.get("status"), "newsletters": items}

    return [generate_newsletter, get_run_status, list_recent_runs, get_newsletter]


def _stringify_dt(value: Any) -> str | None:
    """Mongo returns naive UTC datetimes; emit them as ISO strings so the
    LLM doesn't get a Python `datetime` literal in its tool message."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
