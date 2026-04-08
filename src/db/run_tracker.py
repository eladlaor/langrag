"""
Run Tracker

Tracks workflow runs in MongoDB with fail-soft behavior.
MongoDB failures are logged but don't break the workflow.

Usage (async nodes in LangGraph 1.0+):
    from db.run_tracker import get_tracker

    tracker = get_tracker()
    run_id = await tracker.create_run(data_source, chats, start, end)
    await tracker.complete_run(run_id, output_path, metrics)
"""

import logging
import uuid

from constants import NewsletterVersionType, RunStatus
from custom_types.field_keys import ContentResultKeys, DecryptionResultKeys, DiscussionKeys, MergeGroupKeys, RankingResultKeys
from datetime import UTC

logger = logging.getLogger(__name__)


class RunTracker:
    """Tracks workflow runs in MongoDB. All methods are fail-soft."""

    def __init__(self):
        try:
            self._db = None
            self._runs_repo = None
            self._discussions_repo = None
            self._messages_repo = None
            self._polls_repo = None
            self._initialized = False
        except Exception as e:
            logger.error(f"Unexpected error initializing RunTracker: {e}")
            raise RuntimeError(f"Failed to initialize RunTracker: {e}") from e

    async def _ensure_initialized(self) -> bool:
        """Lazily initializing MongoDB connection."""
        if self._initialized:
            return True

        try:
            from db.connection import get_database
            from db.repositories.runs import RunsRepository
            from db.repositories.discussions import DiscussionsRepository
            from db.repositories.messages import MessagesRepository
            from db.repositories.newsletters import NewslettersRepository
            from db.repositories.polls import PollsRepository

            self._db = await get_database()
            self._runs_repo = RunsRepository(self._db)
            self._discussions_repo = DiscussionsRepository(self._db)
            self._messages_repo = MessagesRepository(self._db)
            self._newsletters_repo = NewslettersRepository(self._db)
            self._polls_repo = PollsRepository(self._db)
            self._initialized = True
            return True
        except Exception as e:
            logger.warning(f"MongoDB not available for run tracking: {e}")
            return False

    @staticmethod
    def _generate_run_id(data_source_name: str, start_date: str, end_date: str) -> str:
        """Generating a unique run ID."""
        short_uuid = str(uuid.uuid4())[:8]
        return f"{data_source_name}_{start_date}_to_{end_date}_{short_uuid}"

    async def create_run(self, data_source_name: str, chat_names: list[str], start_date: str, end_date: str, config: dict | None = None) -> str | None:
        """Creating a new run document."""
        if not await self._ensure_initialized():
            return None

        try:
            run_id = self._generate_run_id(data_source_name, start_date, end_date)
            await self._runs_repo.create_run(run_id=run_id, data_source_name=data_source_name, chat_names=chat_names, start_date=start_date, end_date=end_date, config=config or {})
            logger.info(f"Created run: {run_id}")
            return run_id
        except Exception as e:
            logger.warning(f"Failed to create run: {e}")
            return None

    async def start_run(self, run_id: str) -> bool:
        """Marking a run as started."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.start_run(run_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to start run: {e}")
            return False

    async def update_stage(self, run_id: str, stage: str, status: str = RunStatus.RUNNING, metadata: dict | None = None) -> bool:
        """Updating the current stage of a run."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.update_stage(run_id, stage, status, metadata)
            return True
        except Exception as e:
            logger.warning(f"Failed to update stage: {e}")
            return False

    async def complete_run(self, run_id: str, output_path: str, metrics: dict | None = None) -> bool:
        """Marking a run as completed."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.complete_run(run_id, output_path)
            if metrics:
                await self._runs_repo.update_one({"run_id": run_id}, {"$set": {"metrics": metrics}})
            logger.info(f"Completed run: {run_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to complete run: {e}")
            return False

    async def fail_run(self, run_id: str, error: str) -> bool:
        """Marking a run as failed."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.fail_run(run_id, error)
            return True
        except Exception as e:
            logger.warning(f"Failed to mark run as failed: {e}")
            return False

    async def update_run_diagnostics(self, run_id: str, diagnostic_report: dict) -> bool:
        """
        Storing diagnostic report for a completed run.

        Args:
            run_id: Run identifier
            diagnostic_report: Report from generate_diagnostic_report()

        Returns:
            True if successful, False otherwise (fail-soft)
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            from datetime import datetime

            result = await self._runs_repo.update_one({"run_id": run_id}, {"$set": {"diagnostic_report": diagnostic_report, "diagnostic_report.generated_at": datetime.now(UTC)}})
            logger.info(f"Stored diagnostic report for run: {run_id}")
            return result.modified_count > 0
        except Exception as e:
            logger.warning(f"Failed to store diagnostic report for run {run_id}: {e}")
            return False

    async def store_discussions(self, run_id: str, chat_name: str, discussions: list[dict]) -> int:
        """Storing discussions from a chat."""
        if not run_id or not discussions or not await self._ensure_initialized():
            return 0

        stored = 0
        for idx, disc in enumerate(discussions):
            try:
                # Extracting message info
                messages = disc.get(DiscussionKeys.MESSAGES, [])

                # Building correct message IDs using the messages' own IDs (short IDs from preprocessor)
                # Format: {run_id}_msg_{short_id}
                message_ids = []
                for m in messages:
                    msg_short_id = m.get(DiscussionKeys.ID)
                    if msg_short_id:
                        message_ids.append(f"{run_id}_msg_{msg_short_id}")
                    else:
                        logger.warning(f"Message in discussion {idx} missing 'id' field: {m}")

                # Getting timestamps
                first_ts = messages[0].get("timestamp") if messages else None
                last_ts = messages[-1].get("timestamp") if messages else None

                # Using discussion's own ID if available, otherwise generating one
                disc_id = disc.get(DiscussionKeys.ID, str(idx))
                discussion_id = f"{run_id}_disc_{disc_id}"

                await self._discussions_repo.create_discussion(
                    discussion_id=discussion_id,
                    run_id=run_id,
                    chat_name=chat_name,
                    title=disc.get(DiscussionKeys.TITLE, ""),
                    nutshell=disc.get(DiscussionKeys.NUTSHELL, ""),
                    message_ids=message_ids,
                    ranking_score=float(disc.get(RankingResultKeys.IMPORTANCE_SCORE, 0) or disc.get(RankingResultKeys.RANKING_SCORE, 0)),
                    first_message_timestamp=first_ts,
                    metadata={
                        MergeGroupKeys.REASONING: disc.get(MergeGroupKeys.REASONING, ""),
                        "topics": disc.get("topics", []),
                        "selected": disc.get("selected_for_newsletter", False),
                        DiscussionKeys.NUM_MESSAGES: len(messages),
                        "last_message_timestamp": last_ts,
                    },
                )
                stored += 1
            except Exception as e:
                logger.debug(f"Failed to store discussion {idx}: {e}")
        return stored

    async def store_polls(self, run_id: str, chat_name: str, data_source_name: str, polls: list[dict]) -> int:
        """Storing polls extracted from a chat. Fail-soft."""
        if not run_id or not polls or not await self._ensure_initialized():
            return 0

        stored = 0
        for poll in polls:
            try:
                matrix_event_id = poll.get("matrix_event_id", "")
                poll_id = f"{run_id}_poll_{matrix_event_id}"

                await self._polls_repo.create_poll(
                    poll_id=poll_id,
                    run_id=run_id,
                    chat_name=chat_name,
                    data_source_name=data_source_name,
                    sender=poll.get("sender", ""),
                    timestamp=poll.get("timestamp", 0),
                    question=poll.get("question", ""),
                    matrix_event_id=matrix_event_id,
                    options=poll.get("options", []),
                    total_votes=poll.get("total_votes", 0),
                    unique_voter_count=poll.get("unique_voter_count", 0),
                )
                stored += 1
            except Exception as e:
                logger.debug(f"Failed to store poll {poll.get('matrix_event_id', '?')}: {e}")
        return stored

    async def store_newsletter(self, newsletter_id: str, run_id: str, newsletter_type: str, data_source_name: str, chat_name: str | None, start_date: str, end_date: str, summary_format: str, desired_language: str, json_path: str, md_path: str, html_path: str | None = None, stats: dict | None = None, featured_discussion_ids: list[str] | None = None, version_type: str = NewsletterVersionType.ORIGINAL) -> bool:
        """
        Storing newsletter version in MongoDB.

        Creating new newsletter record for original version,
        updating existing record for enriched/translated versions.

        Args:
            newsletter_id: Unique newsletter identifier
            run_id: Run identifier
            newsletter_type: "per_chat" or "consolidated"
            data_source_name: Data source name
            chat_name: Chat name (None for consolidated)
            start_date: Start date
            end_date: End date
            summary_format: Format identifier
            desired_language: Target language
            json_path: Path to JSON file
            md_path: Path to markdown file
            html_path: Path to HTML file (optional)
            stats: Statistics dictionary
            featured_discussion_ids: Featured discussion IDs
            version_type: "original", "enriched", or "translated"

        Returns:
            True if successful, False otherwise
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            import json
            import os

            # Verifying files exist
            if version_type == NewsletterVersionType.TRANSLATED:
                if not os.path.exists(md_path):
                    logger.warning(f"Translated newsletter file not found: {md_path}")
                    return False
            else:
                if not os.path.exists(json_path):
                    logger.warning(f"Newsletter JSON file not found: {json_path}")
                    return False

            # Reading JSON content (if applicable)
            json_content = None
            if version_type != NewsletterVersionType.TRANSLATED and os.path.exists(json_path):
                with open(json_path, encoding="utf-8") as f:
                    json_content = json.load(f)

            # Reading markdown content
            md_content = None
            if os.path.exists(md_path):
                with open(md_path, encoding="utf-8") as f:
                    md_content = f.read()

            # Reading HTML content (if applicable)
            html_content = None
            if html_path and os.path.exists(html_path):
                with open(html_path, encoding="utf-8") as f:
                    html_content = f.read()

            file_paths = {"json": json_path if version_type != NewsletterVersionType.TRANSLATED else None, "md": md_path, "html": html_path}

            if version_type == NewsletterVersionType.ORIGINAL:
                # Creating new newsletter record
                await self._newsletters_repo.create_newsletter(newsletter_id=newsletter_id, run_id=run_id, newsletter_type=newsletter_type, data_source_name=data_source_name, start_date=start_date, end_date=end_date, summary_format=summary_format, desired_language=desired_language, original_json=json_content, original_markdown=md_content, original_html=html_content, file_paths=file_paths, chat_name=chat_name, stats=stats, featured_discussion_ids=featured_discussion_ids)
                logger.info(f"Stored original newsletter: {newsletter_id}")

            elif version_type == NewsletterVersionType.ENRICHED:
                # Updating with enriched version
                links_added = stats.get(ContentResultKeys.LINKS_ADDED, 0) if stats else 0
                await self._newsletters_repo.add_enriched_version(newsletter_id=newsletter_id, enriched_json=json_content, enriched_markdown=md_content, enriched_html=html_content, file_paths=file_paths, links_added=links_added)
                logger.info(f"Stored enriched newsletter: {newsletter_id}")

            elif version_type == NewsletterVersionType.TRANSLATED:
                # Updating with translated version
                await self._newsletters_repo.add_translated_version(newsletter_id=newsletter_id, translated_markdown=md_content, target_language=desired_language, file_paths=file_paths)
                logger.info(f"Stored translated newsletter: {newsletter_id}")

            return True

        except Exception as e:
            logger.warning(f"Failed to store newsletter {newsletter_id}: {e}")
            return False

    async def update_chat_status(self, run_id: str, chat_name: str, status: str, metadata: dict | None = None) -> bool:
        """
        Updating status for a specific chat within a run.

        Args:
            run_id: Run identifier
            chat_name: Chat name
            status: Status (e.g., "running", "completed", "failed")
            metadata: Additional chat-level metadata

        Returns:
            True if successful, False otherwise
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            from datetime import datetime

            update_doc = {f"chats.{chat_name}.status": status, f"chats.{chat_name}.updated_at": datetime.now(UTC)}
            if metadata:
                for key, value in metadata.items():
                    update_doc[f"chats.{chat_name}.{key}"] = value

            await self._runs_repo.update_one({"run_id": run_id}, {"$set": update_doc})
            return True
        except Exception as e:
            logger.warning(f"Failed to update chat status: {e}")
            return False

    async def update_chat_outputs(self, run_id: str, chat_name: str, output_paths: dict) -> bool:
        """
        Storing output file paths for a chat.

        Args:
            run_id: Run identifier
            chat_name: Chat name
            output_paths: Dict of output file paths

        Returns:
            True if successful, False otherwise
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.update_one({"run_id": run_id}, {"$set": {f"chats.{chat_name}.output_paths": output_paths}})
            return True
        except Exception as e:
            logger.warning(f"Failed to update chat outputs: {e}")
            return False

    async def update_stage_progress(self, run_id: str, stage_name: str, status: str, metadata: dict | None = None) -> bool:
        """
        Updating progress for a specific workflow stage.

        Args:
            run_id: Run identifier
            stage_name: Stage name (e.g., "extraction", "preprocessing")
            status: Stage status ("started", "completed", "failed")
            metadata: Additional stage metadata

        Returns:
            True if successful, False otherwise
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            from datetime import datetime

            timestamp_field = f"stages.{stage_name}.{status}_at"
            update_doc = {f"stages.{stage_name}.status": status, timestamp_field: datetime.now(UTC)}
            if metadata:
                for key, value in metadata.items():
                    update_doc[f"stages.{stage_name}.{key}"] = value

            await self._runs_repo.update_one({"run_id": run_id}, {"$set": update_doc})
            return True
        except Exception as e:
            logger.warning(f"Failed to update stage progress: {e}")
            return False

    async def update_consolidated_outputs(self, run_id: str, output_paths: dict, metadata: dict | None = None) -> bool:
        """
        Storing consolidated newsletter output paths.

        Args:
            run_id: Run identifier
            output_paths: Dict of consolidated output file paths
            metadata: Additional metadata (discussion_count, etc.)

        Returns:
            True if successful, False otherwise
        """
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            update_doc = {"consolidated.output_paths": output_paths}
            if metadata:
                for key, value in metadata.items():
                    update_doc[f"consolidated.{key}"] = value

            await self._runs_repo.update_one({"run_id": run_id}, {"$set": update_doc})
            return True
        except Exception as e:
            logger.warning(f"Failed to update consolidated outputs: {e}")
            return False

    async def store_raw_messages(
        self,
        run_id: str,
        chat_name: str,
        data_source_name: str,
        messages: list[dict],
        classification_map: dict[str, dict] | None = None,
    ) -> int:
        """
        Storing ALL raw extracted messages (pre-preprocessing) with SLM classification metadata.

        Called from slm_prefilter node to persist every message before any filtering occurs.
        Each message gets SLM classification metadata if available.

        Args:
            run_id: Run identifier
            chat_name: Chat name
            data_source_name: Data source (e.g., "langtalks")
            messages: List of raw extracted message dictionaries
            classification_map: Mapping of message_id -> {classification, confidence, reason}.
                                None when SLM is disabled or unavailable.

        Returns:
            Number of messages successfully stored
        """
        if not run_id or not messages or not await self._ensure_initialized():
            return 0

        try:
            docs = []
            for idx, msg in enumerate(messages):
                # Raw messages use 'id' field which is the Matrix event ID
                event_id = msg.get(DiscussionKeys.ID) or msg.get(DecryptionResultKeys.EVENT_ID) or str(idx)
                message_id = f"{run_id}_msg_{event_id}"

                # Look up SLM classification if available
                slm_data = (classification_map or {}).get(str(event_id), {})

                doc = {
                    "message_id": message_id,
                    "run_id": run_id,
                    "chat_name": chat_name,
                    "data_source_name": data_source_name,
                    "sender": msg.get("sender_id") or msg.get("sender") or "",
                    "timestamp": msg.get("timestamp"),
                    "content": msg.get("content", ""),
                    "content_translated": None,
                    "is_translated": False,
                    "slm_classification": slm_data.get("classification"),
                    "slm_confidence": slm_data.get("confidence"),
                    "slm_reason": slm_data.get("reason"),
                }
                docs.append(doc)

            count = await self._messages_repo.insert_batch(docs)
            logger.info(f"Stored {count}/{len(messages)} raw messages for run {run_id}, chat {chat_name}")
            return count
        except Exception as e:
            logger.warning(f"Failed to store raw messages: {e}")
            return 0

    async def store_messages(self, run_id: str, chat_name: str, data_source_name: str, messages: list[dict]) -> int:
        """
        Upserting translated/preprocessed messages in MongoDB.

        Updates existing records (from store_raw_messages) with translation and
        preprocessing data. For messages not previously stored, inserts them as new docs.

        Args:
            run_id: Run identifier
            chat_name: Chat name
            data_source_name: Data source (e.g., "langtalks")
            messages: List of preprocessed/translated message dictionaries

        Returns:
            Number of messages successfully upserted
        """
        if not run_id or not messages or not await self._ensure_initialized():
            return 0

        try:
            docs = []
            for idx, msg in enumerate(messages):
                msg_short_id = msg.get(DiscussionKeys.ID, str(idx))

                # Build message_id using matrix_event_id to match store_raw_messages keys,
                # falling back to the short_id for compatibility
                matrix_event_id = msg.get("matrix_event_id")
                message_id = f"{run_id}_msg_{matrix_event_id}" if matrix_event_id else f"{run_id}_msg_{msg_short_id}"

                doc = {
                    "message_id": message_id,
                    "matrix_event_id": matrix_event_id,
                    "short_id": msg_short_id,
                    "run_id": run_id,
                    "chat_name": chat_name,
                    "data_source_name": data_source_name,
                    "sender": msg.get("sender", ""),
                    "timestamp": msg.get("timestamp"),
                    "content_translated": msg.get("content", ""),
                    "is_translated": True,
                    "urls": msg.get("urls", []),
                    "mentions": msg.get("mentions", []),
                    "replies_to": msg.get("replies_to"),
                    "word_count": len(msg.get("content", "").split()),
                }
                docs.append(doc)

            count = await self._messages_repo.upsert_batch(docs)
            logger.info(f"Upserted {count}/{len(messages)} messages for run {run_id}, chat {chat_name}")
            return count
        except Exception as e:
            logger.warning(f"Failed to upsert messages: {e}")
            return 0


# Singleton
_tracker: RunTracker | None = None


def get_tracker() -> RunTracker:
    """Getting the singleton RunTracker instance for use in async nodes."""
    global _tracker
    if _tracker is None:
        _tracker = RunTracker()
    return _tracker
