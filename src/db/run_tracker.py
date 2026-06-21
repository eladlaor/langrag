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

from pymongo.errors import PyMongoError

from constants import NewsletterVersionType, RunStatus
from custom_types.db_schemas import MessageDocument
from custom_types.field_keys import ContentResultKeys, DbFieldKeys, DecryptionResultKeys, DiscussionKeys, MergeGroupKeys, MessageSourceKeys, PollDbKeys, RankingResultKeys
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
            from db.repositories.raw_discussions import RawDiscussionsRepository
            from db.repositories.messages import MessagesRepository
            from db.repositories.newsletters import NewslettersRepository
            from db.repositories.polls import PollsRepository

            self._db = await get_database()
            self._runs_repo = RunsRepository(self._db)
            self._discussions_repo = DiscussionsRepository(self._db)
            self._raw_discussions_repo = RawDiscussionsRepository(self._db)
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
        except PyMongoError as e:
            logger.warning(f"Failed to start run: {e}")
            return False

    async def update_stage(self, run_id: str, stage: str, status: str = RunStatus.RUNNING, metadata: dict | None = None) -> bool:
        """Updating the current stage of a run."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.update_stage(run_id, stage, status, metadata)
            return True
        except PyMongoError as e:
            logger.warning(f"Failed to update stage: {e}")
            return False

    async def complete_run(self, run_id: str, output_path: str, metrics: dict | None = None) -> bool:
        """Marking a run as completed."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.complete_run(run_id, output_path, metrics)
            logger.info(f"Completed run: {run_id}")
            return True
        except PyMongoError as e:
            logger.warning(f"Failed to complete run: {e}")
            return False

    async def fail_run(self, run_id: str, error: str) -> bool:
        """Marking a run as failed."""
        if not run_id or not await self._ensure_initialized():
            return False

        try:
            await self._runs_repo.fail_run(run_id, error)
            return True
        except PyMongoError as e:
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

            # Stamp generated_at INSIDE the report document. Setting both
            # "diagnostic_report" and "diagnostic_report.generated_at" in one $set
            # is a conflicting-path update that MongoDB rejects outright.
            report_to_store = {**diagnostic_report, DbFieldKeys.GENERATED_AT: datetime.now(UTC)}
            persisted = await self._runs_repo.update_one({DbFieldKeys.RUN_ID: run_id}, {"$set": {DbFieldKeys.DIAGNOSTIC_REPORT: report_to_store}})
            logger.info(f"Stored diagnostic report for run: {run_id}")
            return persisted
        except PyMongoError as e:
            logger.warning(f"Failed to store diagnostic report for run {run_id}: {e}")
            return False

    async def store_discussions(self, run_id: str, chat_name: str, discussions: list[dict], data_source_name: str | None = None) -> int:
        """Storing discussions from a chat.

        Normalizes each discussion into a flat doc dict, then persists the whole
        batch through DiscussionsRepository.create_discussions_bulk — one batched
        embedding call + one bulk upsert, instead of the former per-discussion
        OpenAI-call-plus-insert loop. Fail-fast: a write failure propagates
        (see knowledge/mongodb/MONGODB_REAUDIT_2026_06_18.md).

        data_source_name stamps the community key on each discussion so retrieval
        can pre-filter discussions by community.
        """
        if not run_id or not discussions or not await self._ensure_initialized():
            return 0

        docs = []
        for idx, disc in enumerate(discussions):
            messages = disc.get(DiscussionKeys.MESSAGES, [])

            # Building correct message IDs using the messages' own IDs (short IDs
            # from preprocessor). Format: {run_id}_msg_{short_id}
            message_ids = []
            for m in messages:
                msg_short_id = m.get(DiscussionKeys.ID)
                if msg_short_id:
                    message_ids.append(f"{run_id}_msg_{msg_short_id}")
                else:
                    logger.warning(f"Message in discussion {idx} missing 'id' field: {m}")

            first_ts = messages[0].get(DbFieldKeys.TIMESTAMP) if messages else None
            last_ts = messages[-1].get(DbFieldKeys.TIMESTAMP) if messages else None

            # Using discussion's own ID if available, otherwise generating one
            disc_id = disc.get(DiscussionKeys.ID, str(idx))
            discussion_id = f"{run_id}_disc_{disc_id}"

            docs.append(
                {
                    DbFieldKeys.DISCUSSION_ID: discussion_id,
                    DbFieldKeys.RUN_ID: run_id,
                    DbFieldKeys.CHAT_NAME: chat_name,
                    DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                    DbFieldKeys.TITLE: disc.get(DiscussionKeys.TITLE, ""),
                    DbFieldKeys.NUTSHELL: disc.get(DiscussionKeys.NUTSHELL, ""),
                    DbFieldKeys.MESSAGE_IDS: message_ids,
                    DbFieldKeys.RANKING_SCORE: float(disc.get(RankingResultKeys.IMPORTANCE_SCORE, 0) or disc.get(RankingResultKeys.RANKING_SCORE, 0)),
                    DiscussionKeys.FIRST_MESSAGE_TIMESTAMP: first_ts,
                    DbFieldKeys.METADATA: {
                        MergeGroupKeys.REASONING: disc.get(MergeGroupKeys.REASONING, ""),
                        "topics": disc.get("topics", []),
                        "selected": disc.get("selected_for_newsletter", False),
                        DiscussionKeys.NUM_MESSAGES: len(messages),
                        "last_message_timestamp": last_ts,
                    },
                }
            )

        return await self._discussions_repo.create_discussions_bulk(docs)

    async def store_raw_discussions(self, run_id: str, chat_name: str, data_source_name: str | None, discussions: list[dict]) -> int:
        """Persist the raw, pre-rank/pre-merge per-chat discussions.

        These are the output of separate_discussions (the LLM segmentation of one
        group's messages into threads), captured BEFORE ranking and cross-chat
        merge. Stamped with data_source_name (community) + chat_name (exact group)
        so the raw segmentation is auditable and community-scoped. Idempotent per
        (run_id, chat_name, local_id). Fail-fast: a write error propagates.
        """
        if not run_id or not discussions or not await self._ensure_initialized():
            return 0

        return await self._raw_discussions_repo.store_raw_discussions(
            run_id=run_id,
            chat_name=chat_name,
            data_source_name=data_source_name,
            discussions=discussions,
        )

    async def store_polls(self, run_id: str, chat_name: str, data_source_name: str, polls: list[dict]) -> int:
        """Storing polls extracted from a chat.

        Normalizes each poll into a flat doc dict, then persists the whole batch
        through PollsRepository.create_polls_bulk — one ordered=False bulk upsert
        keyed on poll_id, instead of the former per-poll create()-in-a-loop.
        Fail-fast: a write failure propagates rather than being masked as a
        partial count (mirrors store_messages / store_discussions, see
        knowledge/mongodb/MONGODB_REAUDIT_2026_06_18.md).
        """
        if not run_id or not polls or not await self._ensure_initialized():
            return 0

        docs = []
        for poll in polls:
            matrix_event_id = poll.get(PollDbKeys.MATRIX_EVENT_ID, "")
            docs.append(
                {
                    PollDbKeys.POLL_ID: f"{run_id}_poll_{matrix_event_id}",
                    PollDbKeys.RUN_ID: run_id,
                    PollDbKeys.CHAT_NAME: chat_name,
                    PollDbKeys.DATA_SOURCE_NAME: data_source_name,
                    PollDbKeys.SENDER: poll.get(PollDbKeys.SENDER, ""),
                    PollDbKeys.TIMESTAMP: poll.get(PollDbKeys.TIMESTAMP, 0),
                    PollDbKeys.QUESTION: poll.get(PollDbKeys.QUESTION, ""),
                    PollDbKeys.MATRIX_EVENT_ID: matrix_event_id,
                    PollDbKeys.OPTIONS: poll.get(PollDbKeys.OPTIONS, []),
                    PollDbKeys.TOTAL_VOTES: poll.get(PollDbKeys.TOTAL_VOTES, 0),
                    PollDbKeys.UNIQUE_VOTER_COUNT: poll.get(PollDbKeys.UNIQUE_VOTER_COUNT, 0),
                }
            )

        return await self._polls_repo.create_polls_bulk(docs)

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
    ) -> int:
        """
        Storing ALL raw extracted messages (pre-preprocessing).

        Called from the extract_messages node to persist every message before
        any preprocessing occurs.

        Args:
            run_id: Run identifier
            chat_name: Chat name
            data_source_name: Data source (e.g., "langtalks")
            messages: List of raw extracted message dictionaries

        Returns:
            Number of messages successfully stored
        """
        if not run_id or not messages or not await self._ensure_initialized():
            return 0

        docs = []
        for idx, msg in enumerate(messages):
            # Raw messages use 'id' field which is the Matrix event ID
            event_id = msg.get(DiscussionKeys.ID) or msg.get(DecryptionResultKeys.EVENT_ID) or str(idx)
            message_id = f"{run_id}_msg_{event_id}"

            # Validate through the canonical schema so the persisted document
            # is guaranteed to match MessageDocument (fail-fast on drift).
            doc = MessageDocument(
                **{
                    DbFieldKeys.MESSAGE_ID: message_id,
                    DbFieldKeys.RUN_ID: run_id,
                    DbFieldKeys.CHAT_NAME: chat_name,
                    DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                    DbFieldKeys.SENDER: msg.get(MessageSourceKeys.SENDER_ID) or msg.get(MessageSourceKeys.SENDER) or "",
                    DbFieldKeys.TIMESTAMP: msg.get(MessageSourceKeys.TIMESTAMP),
                    DbFieldKeys.CONTENT: msg.get(MessageSourceKeys.CONTENT, ""),
                    DbFieldKeys.CONTENT_TRANSLATED: None,
                    DbFieldKeys.IS_TRANSLATED: False,
                }
            ).model_dump()
            docs.append(doc)

        # Fail-fast: a write failure must surface, not be masked as "0 stored".
        count = await self._messages_repo.insert_batch(docs)
        logger.info(f"Stored {count}/{len(messages)} raw messages for run {run_id}, chat {chat_name}")
        if count < len(messages):
            logger.warning(f"Partial raw-message persistence: stored {count}/{len(messages)} messages", extra={"run_id": run_id, "chat_name": chat_name, "stored": count, "expected": len(messages)})
        return count

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

        docs = []
        for idx, msg in enumerate(messages):
            msg_short_id = msg.get(MessageSourceKeys.ID, str(idx))

            # Build message_id using matrix_event_id to match store_raw_messages keys,
            # falling back to the short_id for compatibility
            matrix_event_id = msg.get(MessageSourceKeys.MATRIX_EVENT_ID)
            message_id = f"{run_id}_msg_{matrix_event_id}" if matrix_event_id else f"{run_id}_msg_{msg_short_id}"
            translated_content = msg.get(MessageSourceKeys.CONTENT, "")

            # Validate through the canonical schema. exclude_unset keeps this an
            # UPSERT PATCH: only the translated-pass fields are written, so the
            # raw-pass fields (content, slm_*) set earlier are not clobbered.
            doc = MessageDocument(
                **{
                    DbFieldKeys.MESSAGE_ID: message_id,
                    DbFieldKeys.MATRIX_EVENT_ID: matrix_event_id,
                    DbFieldKeys.SHORT_ID: msg_short_id,
                    DbFieldKeys.RUN_ID: run_id,
                    DbFieldKeys.CHAT_NAME: chat_name,
                    DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                    DbFieldKeys.SENDER: msg.get(MessageSourceKeys.SENDER, ""),
                    DbFieldKeys.TIMESTAMP: msg.get(MessageSourceKeys.TIMESTAMP),
                    DbFieldKeys.CONTENT_TRANSLATED: translated_content,
                    DbFieldKeys.IS_TRANSLATED: True,
                    DbFieldKeys.URLS: msg.get(MessageSourceKeys.URLS, []),
                    DbFieldKeys.MENTIONS: msg.get(MessageSourceKeys.MENTIONS, []),
                    DbFieldKeys.REPLIES_TO: msg.get(MessageSourceKeys.REPLIES_TO),
                    DbFieldKeys.WORD_COUNT: len(translated_content.split()),
                }
            ).model_dump(exclude_unset=True)
            docs.append(doc)

        # Fail-fast: surface write failures instead of returning a misleading 0.
        count = await self._messages_repo.upsert_batch(docs)
        logger.info(f"Upserted {count}/{len(messages)} messages for run {run_id}, chat {chat_name}")
        return count


# Singleton
_tracker: RunTracker | None = None


def get_tracker() -> RunTracker:
    """Getting the singleton RunTracker instance for use in async nodes."""
    global _tracker
    if _tracker is None:
        _tracker = RunTracker()
    return _tracker
