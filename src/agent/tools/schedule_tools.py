"""Schedule tools — manage recurring newsletter schedules.

Wraps `src.db.scheduled_newsletters.ScheduledNewsletterManager`. All
operations are ACL-gated on the schedule's `data_source_name` (community);
cross-tenant read AND write are both refused.

`delete_schedule` is destructive; commit 10 will gate it behind a HITL
`interrupt()` so the route handler can prompt the user to confirm.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from agent.auth.acl import assert_user_owns_community
from agent.auth.user_context import current_user_context

logger = logging.getLogger(__name__)


def build_schedule_tools() -> list[BaseTool]:
    """Return the three schedule tools."""

    @tool
    async def create_schedule(
        community: str,
        chats: list[str],
        interval_days: int = 7,
        run_time: str = "09:00",
        desired_language: str = "english",
        summary_format: str = "langtalks_format",
        consolidate_chats: bool = True,
        email_recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a recurring newsletter schedule for one community.

        ACL-gated: the user must own `community`.

        Args:
            community: Community key.
            chats: WhatsApp chat names within the community to include.
            interval_days: Days between runs (e.g., 7 for weekly).
            run_time: HH:MM (24h, UTC) when each run should fire.
            desired_language: Output language.
            summary_format: Newsletter format identifier.
            consolidate_chats: Single consolidated newsletter (True) or
                one per chat (False).
            email_recipients: Optional explicit recipients; when None,
                falls back to the user's configured defaults.

        Returns:
            Dict with the new `schedule_id`.
        """
        ctx = current_user_context()
        assert_user_owns_community(ctx, community)

        # Lazy import: ScheduledNewsletterManager is heavy (drags in
        # APScheduler) and we don't need it for unit-test-shape checks.
        from db.scheduled_newsletters import _get_schedule_manager

        manager = _get_schedule_manager()
        payload: dict[str, Any] = {
            "name": f"{community} — auto-scheduled by agent",
            "data_source_name": community,
            "whatsapp_chat_names_to_include": list(chats),
            "interval_days": int(interval_days),
            "run_time": run_time,
            "desired_language_for_summary": desired_language,
            "summary_format": summary_format,
            "consolidate_chats": bool(consolidate_chats),
            "email_recipients": list(email_recipients) if email_recipients else [],
        }
        schedule_id = await manager.create_schedule(payload)
        logger.info(
            "create_schedule: user_id=%s community=%s schedule_id=%s",
            ctx.user_id,
            community,
            schedule_id,
        )
        return {"schedule_id": schedule_id, "community": community}

    @tool
    async def list_schedules(community: str | None = None) -> list[dict[str, Any]]:
        """List active recurring schedules.

        Always scoped to communities the user owns. Cross-tenant
        schedules are silently filtered out — not visible at all.

        Args:
            community: Optional filter to one community (must be owned).

        Returns:
            List of schedule dicts, each carrying `schedule_id`,
            `name`, `data_source_name`, `interval_days`, `run_time`,
            `enabled`, `next_run`.
        """
        ctx = current_user_context()
        from db.scheduled_newsletters import _get_schedule_manager

        manager = _get_schedule_manager()
        all_schedules = await manager.list_all()
        out: list[dict[str, Any]] = []
        for s in all_schedules:
            ds = s.get("data_source_name", "")
            if not ctx.owns(ds):
                continue
            if community is not None and ds != community:
                continue
            out.append(
                {
                    "schedule_id": str(s.get("_id")),
                    "name": s.get("name"),
                    "data_source_name": ds,
                    "interval_days": s.get("interval_days"),
                    "run_time": s.get("run_time"),
                    "enabled": s.get("enabled"),
                    "next_run": _stringify_dt(s.get("next_run")),
                    "last_run": _stringify_dt(s.get("last_run")),
                }
            )
        return out

    @tool
    async def delete_schedule(schedule_id: str) -> dict[str, Any]:
        """Delete a recurring schedule.

        ACL-gated: the schedule's `data_source_name` must be one the
        user owns. Cross-tenant deletion is refused.

        Destructive — gated by a HITL `interrupt()` so the user must
        approve in the UI before the delete actually fires.

        Args:
            schedule_id: Identifier returned by `create_schedule` or
                `list_schedules`.

        Returns:
            Dict with `deleted: bool`.
        """
        ctx = current_user_context()
        from db.scheduled_newsletters import _get_schedule_manager

        manager = _get_schedule_manager()
        existing = await manager.get_by_id(schedule_id)
        if existing is None:
            return {"deleted": False, "reason": "not_found"}
        ds = existing.get("data_source_name", "")
        if ds and not ctx.owns(ds):
            # Refuse without revealing that the schedule exists.
            return {"deleted": False, "reason": "not_found"}

        # HITL gate: suspend the graph and ask the user to confirm
        # before the destructive delete fires. `interrupt(...)` is
        # captured by the SSE stream handler as `interrupt_required`;
        # the frontend pops a modal and POSTs to /agent/chat/resume
        # with the user's decision ("approve" / "reject").
        decision = interrupt(
            {
                "kind": "confirm",
                "action": "delete_schedule",
                "args": {
                    "schedule_id": schedule_id,
                    "community": ds,
                    "schedule_name": existing.get("name", ""),
                },
            }
        )
        if str(decision).lower() != "approve":
            logger.info(
                "delete_schedule: user_id=%s schedule_id=%s rejected by user",
                ctx.user_id,
                schedule_id,
            )
            return {
                "deleted": False,
                "schedule_id": schedule_id,
                "reason": "rejected_by_user",
            }

        ok = await manager.delete(schedule_id)
        logger.info(
            "delete_schedule: user_id=%s schedule_id=%s ok=%s (approved)",
            ctx.user_id,
            schedule_id,
            ok,
        )
        return {"deleted": bool(ok), "schedule_id": schedule_id}

    return [create_schedule, list_schedules, delete_schedule]


def _stringify_dt(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
