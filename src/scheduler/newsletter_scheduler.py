"""
Newsletter Scheduler

Background scheduler for automated newsletter generation.
Uses APScheduler to check for due schedules and trigger newsletter generation.

This replaces the n8n-based scheduling with a simpler, built-in solution.
"""

import logging
from datetime import datetime, timedelta, UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from constants import DEFAULT_LANGUAGE, SummaryFormats

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


async def check_and_run_schedules() -> None:
    """
    Check for due schedules and execute them.

    This function is called by the scheduler every minute.
    It queries MongoDB for schedules where next_run <= now,
    then triggers newsletter generation for each one.
    """
    try:
        from db.scheduled_newsletters import _get_schedule_manager

        manager = _get_schedule_manager()
        due_schedules = await manager.get_due_schedules()

        if not due_schedules:
            logger.debug("No due schedules found")
            return

        logger.info(f"Found {len(due_schedules)} due schedule(s)")

        for schedule in due_schedules:
            schedule_id = schedule.get("_id")
            schedule_name = schedule.get("name", "unnamed")

            try:
                logger.info(f"Executing schedule: {schedule_name} (ID: {schedule_id})")
                await run_scheduled_newsletter(schedule)
                await manager.mark_complete(schedule_id, success=True)
                logger.info(f"Schedule completed successfully: {schedule_name}")

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Schedule failed: {schedule_name} - {error_msg}")
                await manager.mark_complete(schedule_id, success=False, error_message=error_msg)

    except Exception as e:
        logger.error(f"Error in schedule checker: {e}", exc_info=True)


async def run_scheduled_newsletter(schedule: dict) -> None:
    """
    Run newsletter generation for a schedule.

    Args:
        schedule: Schedule document from MongoDB

    Raises:
        Exception: If newsletter generation fails
    """
    from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph
    from graphs.state_keys import ParallelOrchestratorStateKeys as OrchestratorKeys
    from constants import OutputAction, SCHEDULE_FIELD_INTERVAL_DAYS

    # Calculate date range based on interval
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7))

    # Build state for the orchestrator graph
    state = {
        OrchestratorKeys.START_DATE: start_date.strftime("%Y-%m-%d"),
        OrchestratorKeys.END_DATE: end_date.strftime("%Y-%m-%d"),
        OrchestratorKeys.DATA_SOURCE_NAME: schedule.get("data_source_name"),
        OrchestratorKeys.WHATSAPP_CHAT_NAMES: schedule.get("whatsapp_chat_names_to_include", []),
        OrchestratorKeys.DESIRED_LANGUAGE: schedule.get("desired_language_for_summary", DEFAULT_LANGUAGE),
        OrchestratorKeys.SUMMARY_FORMAT: schedule.get("summary_format", SummaryFormats.LANGTALKS_FORMAT),
        OrchestratorKeys.CONSOLIDATE_CHATS: schedule.get("consolidate_chats", True),
        # Output actions - save locally and send email
        OrchestratorKeys.OUTPUT_ACTIONS: [OutputAction.SAVE_LOCAL, OutputAction.SEND_EMAIL],
        OrchestratorKeys.EMAIL_RECIPIENTS: schedule.get("email_recipients", []),
        # Initialize aggregation fields
        OrchestratorKeys.CHAT_RESULTS: [],
        OrchestratorKeys.CHAT_ERRORS: [],
    }

    # Build config
    import uuid

    thread_id = f"scheduled_{schedule.get('_id')}_{uuid.uuid4().hex[:8]}"

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    logger.info(f"Starting scheduled newsletter generation: " f"{state[OrchestratorKeys.DATA_SOURCE_NAME]} " f"({state[OrchestratorKeys.START_DATE]} to {state[OrchestratorKeys.END_DATE]})")

    # Execute the graph
    graph = await get_parallel_orchestrator_graph()
    result = await graph.ainvoke(state, config)

    # Check for failures
    failed_chats = result.get(OrchestratorKeys.FAILED_CHATS, 0)
    successful_chats = result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)

    if successful_chats == 0 and failed_chats > 0:
        raise RuntimeError(f"All {failed_chats} chats failed")

    logger.info(f"Scheduled newsletter complete: " f"{successful_chats} successful, {failed_chats} failed")


def get_scheduler() -> AsyncIOScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def start_scheduler() -> None:
    """
    Start the newsletter scheduler.

    Should be called during FastAPI app startup.
    """
    scheduler = get_scheduler()

    if scheduler.running:
        logger.warning("Scheduler is already running")
        return

    # Add job to check schedules every minute
    scheduler.add_job(
        check_and_run_schedules,
        trigger=IntervalTrigger(minutes=1),
        id="newsletter_schedule_checker",
        name="Check and run due newsletter schedules",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )

    scheduler.start()
    logger.info("Newsletter scheduler started (checking every 1 minute)")


async def stop_scheduler() -> None:
    """
    Stop the newsletter scheduler.

    Should be called during FastAPI app shutdown.
    """
    scheduler = get_scheduler()

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Newsletter scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if the scheduler is currently running."""
    scheduler = get_scheduler()
    return scheduler.running
