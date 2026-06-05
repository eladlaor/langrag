"""
Batch Worker

Background worker that processes batch API jobs for newsletter generation.
Running as a separate Docker service, polling MongoDB for queued jobs.

Usage:
    python -m background_jobs.batch_worker

The worker:
1. Polling for pending jobs in MongoDB
2. Claiming a job atomically (preventing duplicate processing)
3. Running the newsletter workflow with use_batch_api=True for translation
4. Updating job status on completion/failure
5. Sending webhook notification if configured

Environment Variables:
    BATCH_WORKER_POLL_INTERVAL: Seconds between polls (default: 10)
    BATCH_WORKER_MAX_JOBS: Max concurrent jobs (default: 1)
"""

import asyncio
import logging
import os
import sys
import signal
from datetime import datetime, UTC

import httpx

# Ensuring src is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.batch_jobs import (
    BatchJobStatus,
    _get_manager,
)
from constants import (
    TIMEOUT_BATCH_WORKER,
    HEADER_CONTENT_TYPE,
    CONTENT_TYPE_JSON,
    OUTPUT_DIR_PERIODIC_NEWSLETTER,
    OUTPUT_BASE_DIR_NAME,
    WorkflowNames,
)
from graphs.state_keys import ParallelOrchestratorStateKeys as OrchestratorKeys
from utils.output_paths import build_run_output_dir

logger = logging.getLogger(__name__)

# Worker configuration
POLL_INTERVAL = int(os.getenv("BATCH_WORKER_POLL_INTERVAL", "10"))
MAX_CONCURRENT_JOBS = int(os.getenv("BATCH_WORKER_MAX_JOBS", "1"))

# Graceful shutdown flag
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handling shutdown signals gracefully."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


async def send_webhook_notification(webhook_url: str, job_id: str, status: str, output_dir: str | None = None, error_message: str | None = None) -> bool:
    """
    Sending webhook notification for job completion.

    Args:
        webhook_url: URL to POST notification to
        job_id: The job UUID
        status: Final job status
        output_dir: Output directory (for completed jobs)
        error_message: Error message (for failed jobs)

    Returns:
        True if notification sent successfully
    """
    payload = {
        "event": "batch_job_completed",
        "job_id": job_id,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if output_dir:
        payload["output_dir"] = output_dir
    if error_message:
        payload["error_message"] = error_message

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_BATCH_WORKER) as client:
            response = await client.post(webhook_url, json=payload, headers={HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON})
            response.raise_for_status()
            logger.info(f"Webhook notification sent successfully: {webhook_url}")
            return True

    except Exception as e:
        logger.error(f"Failed to send webhook notification to {webhook_url}: {e}")
        return False


async def send_email_notification(email: str, job_id: str, status: str, output_dir: str | None = None, error_message: str | None = None) -> bool:
    """
    Sending email notification for job completion.

    Using configured SMTP settings from environment.

    Args:
        email: Email address to notify
        job_id: The job UUID
        status: Final job status
        output_dir: Output directory (for completed jobs)
        error_message: Error message (for failed jobs)

    Returns:
        True if email sent successfully
    """
    # TODO: Implement email notification using SMTP settings
    # For now, just log the notification
    logger.info(f"Email notification would be sent to {email}: " f"job_id={job_id}, status={status}, output_dir={output_dir}")
    return True


async def process_batch_job(job: dict) -> tuple[bool, str | None, str | None]:
    """
    Processing a single batch job.

    Running the newsletter generation workflow with batch API enabled for translation.
    Using native async LangGraph 1.0+ ainvoke() for graph execution.

    Args:
        job: Job document from MongoDB

    Returns:
        Tuple of (success, output_dir, error_message)
    """
    job_id = job.get("job_id")
    request = job.get("request", {})

    logger.info(f"Processing batch job: {job_id}")
    logger.info(f"  Data source: {request.get('data_source_name')}")
    logger.info(f"  Date range: {request.get('start_date')} to {request.get('end_date')}")
    logger.info(f"  Chats: {request.get('whatsapp_chat_names_to_include')}")

    try:
        # Importing workflow components
        from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph
        from custom_types.api_schemas import PeriodicNewsletterRequest
        from api.newsletter_gen import build_orchestrator_state

        # Reconstructing request object
        newsletter_request = PeriodicNewsletterRequest(**request)

        # Setting up output directory
        base_output_dir = newsletter_request.output_dir or os.path.join(OUTPUT_BASE_DIR_NAME, OUTPUT_DIR_PERIODIC_NEWSLETTER)
        run_output_dir = build_run_output_dir(base_output_dir, newsletter_request.data_source_name, newsletter_request.start_date, newsletter_request.end_date)

        # Creating output directory
        os.makedirs(run_output_dir, exist_ok=True)

        # Preparing state for parallel orchestrator via the shared builder
        # (single source of truth — also used by the sync/streaming endpoints).
        # The batch worker overrides the workflow name and enables the Batch API
        # so the preprocessing nodes route translation through it.
        state = build_orchestrator_state(
            newsletter_request,
            run_output_dir,
            workflow_name=WorkflowNames.PERIODIC_NEWSLETTER_BATCH,
            use_batch_api=True,
        )

        # Config for workflow
        thread_id = f"batch_job_{job_id}"
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        logger.info(f"Starting workflow for batch job: {job_id}")

        # Invoking the workflow (async - LangGraph 1.0+)
        graph = await get_parallel_orchestrator_graph()
        result = await graph.ainvoke(state, config)

        # Checking results using state key constants
        successful_chats = result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)
        total_chats = result.get(OrchestratorKeys.TOTAL_CHATS, 0)

        logger.info(f"Workflow completed for batch job {job_id}: " f"{successful_chats}/{total_chats} successful")

        if successful_chats == 0 and total_chats > 0:
            # All chats failed
            error_details = result.get(OrchestratorKeys.CHAT_ERRORS, [])
            error_msg = f"All {total_chats} chats failed"
            if error_details:
                first_error = error_details[0].get("error", "Unknown error")
                error_msg += f": {first_error}"
            return False, run_output_dir, error_msg

        return True, run_output_dir, None

    except Exception as e:
        logger.error(f"Error processing batch job {job_id}: {e}", exc_info=True)
        return False, None, str(e)


async def process_job_async(job: dict) -> None:
    """
    Async wrapper for processing a batch job.

    Handling claiming, processing, and status updates.
    Using native async operations (LangGraph 1.0+).
    """
    job_id = job.get("job_id")
    manager = _get_manager()

    try:
        # Claiming the job atomically
        if not await manager.claim_job(job_id):
            logger.debug(f"Could not claim job {job_id} - already claimed")
            return

        logger.info(f"Claimed batch job: {job_id}")

        # Processing the job (native async - LangGraph 1.0+)
        success, output_dir, error_message = await process_batch_job(job)

        # Updating job status based on result
        if success:
            await manager.complete_job(job_id, output_dir)
            logger.info(f"Batch job completed successfully: {job_id}")
        else:
            await manager.fail_job(job_id, error_message or "Unknown error")
            logger.error(f"Batch job failed: {job_id} - {error_message}")

        # Sending notifications
        webhook_url = job.get("webhook_url")
        notification_email = job.get("notification_email")
        final_status = BatchJobStatus.COMPLETED if success else BatchJobStatus.FAILED

        if webhook_url:
            await send_webhook_notification(webhook_url=webhook_url, job_id=job_id, status=final_status, output_dir=output_dir, error_message=error_message)

        if notification_email:
            await send_email_notification(email=notification_email, job_id=job_id, status=final_status, output_dir=output_dir, error_message=error_message)

    except Exception as e:
        logger.error(f"Unexpected error processing job {job_id}: {e}", exc_info=True)
        try:
            await manager.fail_job(job_id, f"Worker error: {e}")
        except Exception as update_err:
            logger.error(f"Failed to update job status after error: {update_err}")


async def worker_loop():
    """
    Main worker loop.

    Polling for pending jobs and processing them using native async operations.
    """
    logger.info(f"Starting batch worker (poll_interval={POLL_INTERVAL}s, max_jobs={MAX_CONCURRENT_JOBS})")

    manager = _get_manager()
    active_tasks = set()

    while not _shutdown_requested:
        try:
            # Cleaning up completed tasks
            done_tasks = {t for t in active_tasks if t.done()}
            for task in done_tasks:
                try:
                    await task  # Retrieving any exceptions
                except Exception as e:
                    logger.error(f"Task completed with error: {e}")
            active_tasks -= done_tasks

            # Checking if we can accept more jobs
            if len(active_tasks) >= MAX_CONCURRENT_JOBS:
                logger.debug(f"At max capacity ({MAX_CONCURRENT_JOBS} jobs), waiting...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Getting pending jobs (async)
            available_slots = MAX_CONCURRENT_JOBS - len(active_tasks)
            jobs = await manager.get_pending_jobs(limit=available_slots)

            if jobs:
                logger.info(f"Found {len(jobs)} pending jobs, processing...")

                for job in jobs:
                    if _shutdown_requested:
                        break

                    task = asyncio.create_task(process_job_async(job))
                    active_tasks.add(task)

            # Sleeping before next poll
            await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.error(f"Error in worker loop: {e}", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    # Graceful shutdown - wait for active tasks
    if active_tasks:
        logger.info(f"Waiting for {len(active_tasks)} active tasks to complete...")
        await asyncio.gather(*active_tasks, return_exceptions=True)

    logger.info("Batch worker shut down gracefully")


def main():
    """Entry point for the batch worker."""
    # Setting up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])

    # Reducing noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Setting up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("=" * 60)
    logger.info("Batch Worker Starting")
    logger.info("=" * 60)

    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
