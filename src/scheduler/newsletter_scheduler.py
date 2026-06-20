"""
Newsletter Scheduler (change-stream driven)

Replaces the every-minute "discover due schedules" poll with:
  1. One APScheduler DateTrigger job per enabled MongoDB schedule, keyed by
     schedule_id. APScheduler fires at the exact next_run instant.
  2. A background MongoDB change stream on `scheduled_newsletters` that keeps
     the in-memory job set in sync with the collection: inserts add jobs,
     updates reschedule them, deletes/disables remove them.

The poll loop is gone. APScheduler itself does time-based firing; the change
stream does discovery. On any change-stream connection loss we fail-fast in
the watcher task and let supervisor logic (startup retry / FastAPI lifespan
restart) decide how to recover, after a brief reconcile-from-scratch.
"""

import asyncio
import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from pymongo import ReadPreference

from constants import (
    CHANGE_STREAM_RECONNECT_DELAY_SECONDS,
    ChangeStreamOperation,
    COLLECTION_SCHEDULED_NEWSLETTERS,
    DEFAULT_LANGUAGE,
    OutputAction,
    SCHEDULE_FIELD_INTERVAL_DAYS,
    SCHEDULER_JOB_ID_PREFIX,
    SummaryFormats,
)
from custom_types.field_keys import DbFieldKeys, ScheduleDocumentKeys

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_change_stream_task: asyncio.Task | None = None
_shutdown_event: asyncio.Event | None = None


def _job_id_for(schedule_id: str) -> str:
    return f"{SCHEDULER_JOB_ID_PREFIX}{schedule_id}"


def _schedule_doc_id_as_str(doc: dict) -> str:
    raw = doc.get(ScheduleDocumentKeys.DOCUMENT_ID)
    return str(raw) if raw is not None else ""


async def run_scheduled_newsletter(schedule: dict) -> None:
    """Run newsletter generation for a schedule document.

    Args:
        schedule: Schedule document from MongoDB (may have ObjectId _id).

    Raises:
        Exception: If newsletter generation fails (fail-fast for the caller).
    """
    from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph
    from graphs.state_keys import ParallelOrchestratorStateKeys as OrchestratorKeys

    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7))

    state = {
        OrchestratorKeys.START_DATE: start_date.strftime("%Y-%m-%d"),
        OrchestratorKeys.END_DATE: end_date.strftime("%Y-%m-%d"),
        OrchestratorKeys.DATA_SOURCE_NAME: schedule.get(ScheduleDocumentKeys.DATA_SOURCE_NAME),
        OrchestratorKeys.CHAT_NAMES: schedule.get(ScheduleDocumentKeys.WHATSAPP_CHAT_NAMES_TO_INCLUDE, []),
        OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY: schedule.get(ScheduleDocumentKeys.DESIRED_LANGUAGE_FOR_SUMMARY, DEFAULT_LANGUAGE),
        OrchestratorKeys.SUMMARY_FORMAT: schedule.get(ScheduleDocumentKeys.SUMMARY_FORMAT, SummaryFormats.LANGTALKS_FORMAT),
        OrchestratorKeys.CONSOLIDATE_CHATS: schedule.get(ScheduleDocumentKeys.CONSOLIDATE_CHATS, True),
        OrchestratorKeys.OUTPUT_ACTIONS: [OutputAction.SAVE_LOCAL, OutputAction.SEND_EMAIL],
        OrchestratorKeys.EMAIL_RECIPIENTS: schedule.get(ScheduleDocumentKeys.EMAIL_RECIPIENTS, []),
        OrchestratorKeys.CHAT_RESULTS: [],
        OrchestratorKeys.CHAT_ERRORS: [],
    }

    import uuid

    thread_id = f"scheduled_{_schedule_doc_id_as_str(schedule)}_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    logger.info(
        f"Starting scheduled newsletter generation: "
        f"{state[OrchestratorKeys.DATA_SOURCE_NAME]} "
        f"({state[OrchestratorKeys.START_DATE]} to {state[OrchestratorKeys.END_DATE]})"
    )

    graph = await get_parallel_orchestrator_graph()
    result = await graph.ainvoke(state, config)

    failed_chats = result.get(OrchestratorKeys.FAILED_CHATS, 0)
    successful_chats = result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)

    if successful_chats == 0 and failed_chats > 0:
        raise RuntimeError(f"All {failed_chats} chats failed")

    logger.info(f"Scheduled newsletter complete: {successful_chats} successful, {failed_chats} failed")


async def _execute_schedule_by_id(schedule_id: str) -> None:
    """APScheduler callback. Loads the schedule fresh from MongoDB (so we
    pick up the latest config) and runs it, then marks complete. The
    `mark_complete` update bumps `next_run` in MongoDB; the change-stream
    watcher then re-registers the next DateTrigger fire.
    """
    from db.scheduled_newsletters import _get_schedule_manager

    manager = _get_schedule_manager()
    schedule = await manager.get_by_id(schedule_id)
    if not schedule:
        logger.warning(f"Schedule disappeared before execution: {schedule_id}")
        return
    if not schedule.get(DbFieldKeys.ENABLED, True):
        logger.info(f"Schedule disabled before execution, skipping: {schedule_id}")
        return

    schedule_name = schedule.get(ScheduleDocumentKeys.NAME, "unnamed")
    try:
        logger.info(f"Executing schedule: {schedule_name} (ID: {schedule_id})")
        await run_scheduled_newsletter(schedule)
        await manager.mark_complete(schedule_id, success=True)
        logger.info(f"Schedule completed successfully: {schedule_name}")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Schedule failed: {schedule_name} - {error_msg}", exc_info=True)
        await manager.mark_complete(schedule_id, success=False, error_message=error_msg)


def _register_schedule_job(scheduler: AsyncIOScheduler, schedule: dict) -> None:
    """Add or replace an APScheduler DateTrigger for the schedule's next_run.

    Disabled schedules and schedules with a past next_run that has already
    been re-projected by mark_complete are still registered for their actual
    next_run; APScheduler will fire immediately on past dates, which is the
    desired "catch up" behavior on cold start.
    """
    schedule_id = _schedule_doc_id_as_str(schedule)
    if not schedule_id:
        logger.warning("Skipping schedule with missing _id")
        return

    if not schedule.get(DbFieldKeys.ENABLED, True):
        _remove_schedule_job(scheduler, schedule_id)
        return

    next_run = schedule.get(DbFieldKeys.NEXT_RUN)
    if next_run is None:
        logger.warning(f"Schedule {schedule_id} has no next_run; not registering")
        return

    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=UTC)

    job_id = _job_id_for(schedule_id)
    scheduler.add_job(
        _execute_schedule_by_id,
        trigger=DateTrigger(run_date=next_run),
        args=[schedule_id],
        id=job_id,
        name=f"Newsletter schedule: {schedule.get(ScheduleDocumentKeys.NAME, schedule_id)}",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.debug(f"Registered job {job_id} -> {next_run.isoformat()}")


def _remove_schedule_job(scheduler: AsyncIOScheduler, schedule_id: str) -> None:
    job_id = _job_id_for(schedule_id)
    try:
        scheduler.remove_job(job_id)
        logger.debug(f"Removed job {job_id}")
    except Exception:  # noqa: BLE001
        # apscheduler raises JobLookupError; treat absence as a no-op.
        pass


async def _reconcile_jobs_from_db(scheduler: AsyncIOScheduler) -> None:
    """Full sync: drop every newsletter-schedule job and rebuild from
    MongoDB. Called on startup and on any change-stream resume failure.
    """
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(SCHEDULER_JOB_ID_PREFIX):
            scheduler.remove_job(job.id)

    from db.scheduled_newsletters import _get_schedule_manager

    manager = _get_schedule_manager()
    schedules = await manager.list_all()
    registered = 0
    for schedule in schedules:
        if not schedule.get(DbFieldKeys.ENABLED, True):
            continue
        _register_schedule_job(scheduler, schedule)
        registered += 1
    logger.info(f"Reconciled {registered} enabled newsletter schedule(s) into APScheduler")


async def _change_stream_watcher() -> None:
    """Long-running task: watch `scheduled_newsletters` and mirror changes
    into APScheduler. Fail-fast on connection loss; the outer loop reconciles
    from scratch and re-opens the stream.
    """
    from db.connection import get_database

    scheduler = get_scheduler()

    while not _shutdown_event.is_set():
        try:
            db = await get_database()
            # Pin the change-stream source to the primary so the watcher never
            # opens against a lagging secondary and misses or reorders events.
            collection = db.get_collection(COLLECTION_SCHEDULED_NEWSLETTERS, read_preference=ReadPreference.PRIMARY)

            # `fullDocument='updateLookup'` is required so update events carry
            # the post-image with the new next_run/enabled values.
            # watch() is a coroutine in the pymongo native-async API; it must be
            # awaited to obtain the AsyncChangeStream before entering it.
            change_stream = await collection.watch(
                full_document="updateLookup",
            )
            async with change_stream as stream:
                logger.info("Change stream open on scheduled_newsletters")
                await _reconcile_jobs_from_db(scheduler)

                async for change in stream:
                    if _shutdown_event.is_set():
                        break
                    await _apply_change(scheduler, change)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            # Fail-fast surface: error log carries enough context for the
            # operator to act. We do not silently retry forever; we sleep a
            # bounded interval, reconcile from scratch, and try once more.
            logger.error(
                f"Change stream on {COLLECTION_SCHEDULED_NEWSLETTERS} failed: {e}. "
                f"Reconciling from scratch and re-opening in "
                f"{CHANGE_STREAM_RECONNECT_DELAY_SECONDS}s.",
                exc_info=True,
            )
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(), timeout=CHANGE_STREAM_RECONNECT_DELAY_SECONDS
                )
                return
            except TimeoutError:
                continue


async def _apply_change(scheduler: AsyncIOScheduler, change: dict[str, Any]) -> None:
    op = change.get("operationType")
    doc_key = change.get("documentKey", {})
    raw_id = doc_key.get(ScheduleDocumentKeys.DOCUMENT_ID)
    schedule_id = str(raw_id) if raw_id is not None else ""
    if not schedule_id:
        logger.warning(f"Change event with no documentKey._id: op={op}")
        return

    if op == ChangeStreamOperation.DELETE:
        _remove_schedule_job(scheduler, schedule_id)
        return

    if op in (
        ChangeStreamOperation.INSERT,
        ChangeStreamOperation.UPDATE,
        ChangeStreamOperation.REPLACE,
    ):
        full_doc = change.get("fullDocument")
        if not full_doc:
            # Updates without fullDocument shouldn't happen with updateLookup,
            # but a deleted-then-event race can produce this. Skip safely.
            logger.debug(f"Skipping change with no fullDocument: op={op}, id={schedule_id}")
            return
        _register_schedule_job(scheduler, full_doc)


def get_scheduler() -> AsyncIOScheduler:
    """Get the global APScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def start_scheduler() -> None:
    """Start APScheduler and the MongoDB change-stream watcher.

    Should be called once during FastAPI app startup.
    """
    global _change_stream_task, _shutdown_event

    scheduler = get_scheduler()
    if scheduler.running:
        logger.warning("Scheduler is already running")
        return

    scheduler.start()
    logger.info("APScheduler started (DateTrigger per schedule, no discovery poll)")

    _shutdown_event = asyncio.Event()
    _change_stream_task = asyncio.create_task(
        _change_stream_watcher(), name="newsletter_schedule_change_stream"
    )


async def stop_scheduler() -> None:
    """Stop the change-stream watcher and APScheduler.

    Should be called once during FastAPI app shutdown.
    """
    global _change_stream_task, _shutdown_event

    if _shutdown_event is not None:
        _shutdown_event.set()
    if _change_stream_task is not None:
        _change_stream_task.cancel()
        try:
            await _change_stream_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _change_stream_task = None
    _shutdown_event = None

    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Newsletter scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if the scheduler is currently running."""
    scheduler = get_scheduler()
    return scheduler.running


async def check_and_run_schedules() -> None:
    """Manual trigger: re-execute every overdue or already-fired schedule.

    Retained as an API affordance (POST /api/schedules/trigger). Implemented
    on top of a one-shot reconcile so the change-stream-driven model stays
    authoritative: any schedule whose next_run is now in the past will be
    fired by APScheduler immediately upon registration.
    """
    scheduler = get_scheduler()
    await _reconcile_jobs_from_db(scheduler)
