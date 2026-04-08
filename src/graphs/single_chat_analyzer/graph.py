"""
Newsletter Generation Workflow - LangGraph 1.0 Implementation

This module implementing the complete newsletter generation pipeline as a LangGraph StateGraph.
Processing individual chats through extraction, SLM pre-filtering, preprocessing, translation,
discussion separation, ranking, content generation, link enrichment, and final translation stages.

Workflow: Periodic Newsletter (Multi-day date range)
Pipeline: extract → slm_prefilter → extract_images → preprocess → translate → separate → rank → associate_images → generate → enrich_links → translate_final

SLM Pre-filtering (optional, controlled by SLM_ENABLED):
- Uses local Ollama SLM to classify messages as KEEP/FILTER/UNCERTAIN
- Reduces expensive LLM API calls by 15-30% by filtering low-quality messages
- Fail-soft: if SLM unavailable, continues without filtering
- Fail-safe: UNCERTAIN messages continue to LLM pipeline

Architecture:
- Linear flow (no conditional routing)
- Using async nodes for native async I/O (LangGraph 1.0+)
- Checking file existence within nodes (not routing logic)
- Using fail-fast error handling
- Enabling checkpointing for resumability
- rank_discussions node invoking discussions_ranker subgraph
- enrich_with_links node invoking link_enricher subgraph
"""

import os
import logging
import re
import json

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END


from db.run_tracker import get_tracker

from config import get_settings
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.single_chat_analyzer.image_extraction import extract_images_node
from graphs.single_chat_analyzer.associate_images import associate_images_node
from graphs.single_chat_analyzer.slm_enrichment import slm_enrichment_node
from graphs.state_keys import SingleChatStateKeys as Keys
from graphs.subgraphs.state import (
    create_ranker_state_from_single_chat,
    create_enricher_state_from_single_chat,
)
from graphs.subgraphs.discussions_ranker import discussions_ranker_graph
from graphs.subgraphs.link_enricher import link_enricher_graph
from utils.validation import validate_single_chat_state
from utils.run_diagnostics import get_diagnostics
from api.sse import with_cache_check, with_progress, with_logging, STAGE_EXTRACT, STAGE_PREPROCESS, STAGE_TRANSLATE, STAGE_SEPARATE, STAGE_RANK, STAGE_GENERATE, STAGE_ENRICH, STAGE_TRANSLATE_FINAL
from observability.metrics import with_metrics
from core.ingestion.extractors.beeper import RawDataExtractorBeeper
from core.ingestion.preprocessors.factory import DataProcessorFactory
from core.generation.generators.factory import ContentGeneratorFactory
from observability import langfuse_span, extract_trace_context
from constants import (
    DataSources,
    PreprocessingOperations,
    ContentGenerationOperations,
    NewsletterType,
    NewsletterVersionType,
    WorkflowNames,
    NodeNames,
    MESSAGING_PLATFORM_WHATSAPP,
    EXTRACTION_STRATEGY_GROUP_CHAT,
    DEFAULT_LANGUAGE,
    DIR_NAME_EXTRACTED,
    DIR_NAME_PREPROCESSED,
    DIR_NAME_TRANSLATED,
    DIR_NAME_SEPARATE_DISCUSSIONS,
    DIR_NAME_DISCUSSIONS_RANKING,
    DIR_NAME_NEWSLETTER,
    DIR_NAME_LINK_ENRICHMENT,
    OUTPUT_FILENAME_MESSAGES_PROCESSED,
    OUTPUT_FILENAME_MESSAGES_TRANSLATED,
    OUTPUT_FILENAME_SEPARATE_DISCUSSIONS,
    OUTPUT_FILENAME_DISCUSSIONS_RANKING,
    OUTPUT_FILENAME_NEWSLETTER_JSON,
    OUTPUT_FILENAME_NEWSLETTER_MD,
    OUTPUT_FILENAME_NEWSLETTER_HTML,
    OUTPUT_FILENAME_ENRICHED_SUMMARY_JSON,
    OUTPUT_FILENAME_ENRICHED_SUMMARY_MD,
    OUTPUT_FILENAME_POLLS,
    RESULT_KEY_NEWSLETTER_SUMMARY_PATH,
    RESULT_KEY_MARKDOWN_PATH,
    RESULT_KEY_HTML_PATH,
    DIAGNOSTIC_CATEGORY_EXTRACTION,
    WORKFLOW_NAME_NEWSLETTER_GENERATION,
)
from custom_types.field_keys import RankingResultKeys, ContentResultKeys, DiscussionKeys
from graphs.single_chat_analyzer.generate_content_helpers import (
    validate_ranking_file,
    validate_discussions_file,
    load_ranking_data,
    load_featured_discussions,
    load_non_featured_discussions,
    initialize_mongodb_repository,
    validate_content_generation_output,
    load_newsletter_for_evaluation,
    score_newsletter_if_available,
    log_mongodb_persistence_success,
)
from graphs.single_chat_analyzer.slm_prefilter import slm_prefilter_node


# Configuring logging
logger = logging.getLogger(__name__)


# ============================================================================
# NODE IMPLEMENTATIONS
# ============================================================================

# NOTE: ensure_valid_session node removed - now running once at orchestrator level (parallel_orchestrator.py)
# Preventing parallel login attempts from all workers that cause rate limiting


@with_logging
@with_progress(STAGE_EXTRACT, start_message="Setting up output directories...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.SETUP_DIRECTORIES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
def setup_directories(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Creating all output directories and populating expected file paths.

    This node initializing the directory structure for the workflow and setting
    all expected file paths based on workflow type (periodic vs. daily).

    Fail-Fast Conditions:
    - output_dir is not writable
    - Directory creation fails

    Returns:
        dict: Directory paths and expected file paths to merge into state
    """
    logger.info("Node: setup_directories - Starting")

    # Validating required state fields
    validate_single_chat_state(state, required=[Keys.CHAT_NAME, Keys.OUTPUT_DIR, Keys.START_DATE, Keys.END_DATE, Keys.WORKFLOW_NAME, Keys.DESIRED_LANGUAGE_FOR_SUMMARY])

    output_dir = state[Keys.OUTPUT_DIR]
    chat_name = state[Keys.CHAT_NAME]
    start_date = state[Keys.START_DATE]
    end_date = state[Keys.END_DATE]
    workflow_name = state[Keys.WORKFLOW_NAME]
    desired_language = state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY]

    # Determining file naming convention based on workflow type
    # Sanitizing chat name for filesystem safety (removing/replacing unsafe characters)
    secure_chat_name = re.sub(r'[<>:"/\\|?*]', "_", chat_name).replace(" ", "_").replace("#", "")
    # Using date range format for periodic newsletter
    date_suffix = f"{start_date}_to_{end_date}"

    # Creating directory structure
    dirs = {
        Keys.EXTRACTION_DIR: os.path.join(output_dir, DIR_NAME_EXTRACTED),
        Keys.PREPROCESS_DIR: os.path.join(output_dir, DIR_NAME_PREPROCESSED),
        Keys.TRANSLATION_DIR: os.path.join(output_dir, DIR_NAME_TRANSLATED),
        Keys.SEPARATE_DISCUSSIONS_DIR: os.path.join(output_dir, DIR_NAME_SEPARATE_DISCUSSIONS),
        Keys.DISCUSSIONS_RANKING_DIR: os.path.join(output_dir, DIR_NAME_DISCUSSIONS_RANKING),
        Keys.CONTENT_DIR: os.path.join(output_dir, DIR_NAME_NEWSLETTER),
        Keys.LINK_ENRICHMENT_DIR: os.path.join(output_dir, DIR_NAME_LINK_ENRICHMENT),
        Keys.FINAL_TRANSLATED_CONTENT_DIR: os.path.join(output_dir, f"final_{desired_language}_translated_summary"),
    }

    # Creating all directories
    for dir_key, dir_path in dirs.items():
        try:
            os.makedirs(dir_path, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Failed to create directory {dir_path}: {e}")

    # Defining expected file paths
    expected_files = {
        Keys.EXPECTED_EXTRACTED_FILE: os.path.join(dirs[Keys.EXTRACTION_DIR], "decrypted_messages", f"decrypted_{secure_chat_name}_{date_suffix}.json"),
        Keys.EXPECTED_PREPROCESSED_FILE: os.path.join(dirs[Keys.PREPROCESS_DIR], OUTPUT_FILENAME_MESSAGES_PROCESSED),
        Keys.EXPECTED_TRANSLATED_FILE: os.path.join(dirs[Keys.TRANSLATION_DIR], OUTPUT_FILENAME_MESSAGES_TRANSLATED),
        Keys.EXPECTED_SEPARATE_DISCUSSIONS_FILE: os.path.join(dirs[Keys.SEPARATE_DISCUSSIONS_DIR], OUTPUT_FILENAME_SEPARATE_DISCUSSIONS),
        Keys.EXPECTED_DISCUSSIONS_RANKING_FILE: os.path.join(dirs[Keys.DISCUSSIONS_RANKING_DIR], OUTPUT_FILENAME_DISCUSSIONS_RANKING),
        Keys.EXPECTED_NEWSLETTER_JSON: os.path.join(dirs[Keys.CONTENT_DIR], OUTPUT_FILENAME_NEWSLETTER_JSON),
        Keys.EXPECTED_NEWSLETTER_MD: os.path.join(dirs[Keys.CONTENT_DIR], OUTPUT_FILENAME_NEWSLETTER_MD),
        Keys.EXPECTED_NEWSLETTER_HTML: os.path.join(dirs[Keys.CONTENT_DIR], OUTPUT_FILENAME_NEWSLETTER_HTML) if workflow_name == WorkflowNames.PERIODIC_NEWSLETTER else None,
        Keys.EXPECTED_ENRICHED_NEWSLETTER_JSON: os.path.join(dirs[Keys.LINK_ENRICHMENT_DIR], OUTPUT_FILENAME_ENRICHED_SUMMARY_JSON),
        Keys.EXPECTED_ENRICHED_NEWSLETTER_MD: os.path.join(dirs[Keys.LINK_ENRICHMENT_DIR], OUTPUT_FILENAME_ENRICHED_SUMMARY_MD),
        Keys.EXPECTED_FINAL_TRANSLATED_FILE: os.path.join(dirs[Keys.FINAL_TRANSLATED_CONTENT_DIR], f"{desired_language}_translated_summary.md"),
    }

    # Creating nested directory for extraction
    os.makedirs(os.path.dirname(expected_files[Keys.EXPECTED_EXTRACTED_FILE]), exist_ok=True)

    logger.info(f"Setup directories for workflow: {workflow_name} - {output_dir}")

    # Merging directory paths and expected file paths into state
    return {**dirs, **expected_files}


@with_logging
@with_progress(STAGE_EXTRACT, start_message="Extracting messages from Beeper...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.EXTRACT_MESSAGES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_EXTRACTED_FILE, force_refresh_key=Keys.FORCE_REFRESH_EXTRACTION, output_keys={Keys.EXTRACTED_FILE_PATH: Keys.EXPECTED_EXTRACTED_FILE})
async def extract_messages(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Extracting WhatsApp messages from Beeper/Matrix API.

    LangGraph 1.0: Using native async node (no sync wrappers).

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events (in_progress, completed, failed)
    - @with_cache_check: Skipping if expected_extracted_file exists

    Fail-Fast Conditions:
    - Beeper authentication fails
    - Chat room not found
    - Network errors
    - Invalid date range

    Returns:
        dict: extracted_file_path, reused_existing flag
    """
    # Validating required state fields
    validate_single_chat_state(state, required=[Keys.CHAT_NAME, Keys.DATA_SOURCE_NAME, Keys.START_DATE, Keys.END_DATE, Keys.EXTRACTION_DIR])

    chat_name = state[Keys.CHAT_NAME]
    source_name = state[Keys.DATA_SOURCE_NAME]
    start_date = state[Keys.START_DATE]
    end_date = state[Keys.END_DATE]
    extraction_dir = state[Keys.EXTRACTION_DIR]

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.EXTRACT_MESSAGES, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "start_date": start_date, "end_date": end_date}, metadata={"source_name": source_name}) as span:
        # Getting database connection for MongoDB cache
        from db.connection import get_database

        db = await get_database()

        worker_store_path = state.get(Keys.WORKER_STORE_PATH)
        raw_data_extractor = RawDataExtractorBeeper(
            source_name=source_name,
            database=db,
            store_path_override=worker_store_path,
        )

        # LangGraph 1.0: Using direct async call (no multiprocessing)
        try:
            decrypted_file_path = await raw_data_extractor.extract_messages(messaging_platform=MESSAGING_PLATFORM_WHATSAPP, extraction_strategy_name=EXTRACTION_STRATEGY_GROUP_CHAT, groupchat_name=chat_name, start_date=start_date, end_date=end_date, output_dir=extraction_dir)
        finally:
            # Cleanup per-worker store copy to avoid disk bloat
            if worker_store_path and os.path.exists(worker_store_path):
                import shutil

                shutil.rmtree(worker_store_path)
                logger.info(f"Cleaned up worker store copy: {worker_store_path}")

        if not decrypted_file_path or not os.path.exists(decrypted_file_path):
            raise RuntimeError(f"Extraction returned invalid file path: {decrypted_file_path}")

        # Checking message count and adding diagnostic if unexpectedly low
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
        message_count = None
        try:
            with open(decrypted_file_path, encoding="utf-8") as f:
                messages = json.load(f)
                message_count = len(messages) if isinstance(messages, list) else 0

                # Emitting diagnostic: Low message count warning
                if mongodb_run_id and message_count < 10:
                    diagnostics = get_diagnostics(mongodb_run_id)
                    diagnostics.info(category=DIAGNOSTIC_CATEGORY_EXTRACTION, message=f"Low message count: only {message_count} messages extracted for date range {start_date} to {end_date}", node_name="extract_messages", details={"message_count": message_count, "chat_name": chat_name, "date_range": f"{start_date} to {end_date}"})
        except Exception as e:
            logger.warning(f"Failed to check message count: {e}")

        result = {Keys.EXTRACTED_FILE_PATH: decrypted_file_path, Keys.REUSED_EXISTING: False, Keys.MESSAGE_COUNT: message_count}

        # Updating span with output
        if span:
            span.update(output={"file_path": decrypted_file_path, "exists": os.path.exists(decrypted_file_path), "message_count": message_count})

        return result


@with_logging
@with_progress(STAGE_PREPROCESS, start_message="Parsing messages and extracting metadata...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.PREPROCESS_MESSAGES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_PREPROCESSED_FILE, force_refresh_key=Keys.FORCE_REFRESH_PREPROCESSING, output_keys={Keys.PREPROCESSED_FILE_PATH: Keys.EXPECTED_PREPROCESSED_FILE})
async def preprocess_messages(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Parsing and standardizing raw WhatsApp messages.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_preprocessed_file exists

    Fail-Fast Conditions:
    - Input file not found or unreadable
    - JSON parsing errors
    - Invalid message format

    Returns:
        dict: preprocessed_file_path, message_count
    """
    data_source_path = state[Keys.EXTRACTED_FILE_PATH]
    if not os.path.exists(data_source_path):
        raise FileNotFoundError(f"Extracted file not found: {data_source_path}")

    data_source_name = state[Keys.DATA_SOURCE_NAME]
    chat_name = state[Keys.CHAT_NAME]
    preprocess_dir = state[Keys.PREPROCESS_DIR]
    expected_file = state[Keys.EXPECTED_PREPROCESSED_FILE]

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.PREPROCESS_MESSAGES, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "source_file": data_source_path}, metadata={"source_name": data_source_name}) as span:
        preprocessor = DataProcessorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=chat_name)

        await preprocessor.preprocess_data(
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            data_source_path=data_source_path,
            preprocessing_operations=[
                PreprocessingOperations.PARSE_AND_STANDARDIZE_RAW_WHATSAPP_MESSAGES_WITH_STATS,
            ],
            output_dir=preprocess_dir,
            chat_name=chat_name,
            data_source_name=data_source_name,
        )

        if not os.path.exists(expected_file):
            raise RuntimeError(f"Preprocessing did not create expected file: {expected_file}")

        # Counting messages for state propagation (NOT persisting to MongoDB yet - waiting for translation)
        message_count = None
        try:
            with open(expected_file) as f:
                messages = json.load(f)
                message_count = len(messages) if isinstance(messages, list) else 0
        except Exception as e:
            logger.warning(f"Failed to load messages: {e}")

        # Persist extracted polls to MongoDB (fail-soft)
        try:
            polls_file = os.path.join(preprocess_dir, OUTPUT_FILENAME_POLLS)
            mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
            if mongodb_run_id and os.path.exists(polls_file):
                with open(polls_file) as f:
                    polls = json.load(f)
                if polls:
                    from db.run_tracker import get_tracker
                    tracker = get_tracker()
                    stored_count = await tracker.store_polls(run_id=mongodb_run_id, chat_name=chat_name, data_source_name=data_source_name, polls=polls)
                    logger.info(f"Persisted {stored_count}/{len(polls)} polls to MongoDB")
        except Exception as e:
            logger.warning(f"Failed to persist polls to MongoDB: {e}")

        result = {Keys.PREPROCESSED_FILE_PATH: expected_file, Keys.MESSAGE_COUNT: message_count}

        # Updating span with output
        if span:
            span.update(output={"message_count": message_count, "file_path": expected_file})

        return result


@with_logging
@with_progress(STAGE_TRANSLATE, start_message="Translating messages to English...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.TRANSLATE_MESSAGES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_TRANSLATED_FILE, force_refresh_key=Keys.FORCE_REFRESH_TRANSLATION, output_keys={Keys.TRANSLATED_FILE_PATH: Keys.EXPECTED_TRANSLATED_FILE})
async def translate_messages(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Translating messages to English using OpenAI API.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_translated_file exists

    Fail-Fast Conditions:
    - OpenAI API errors (rate limits, auth, etc.)
    - Input file not found
    - Invalid message format

    Returns:
        dict: translated_file_path
    """
    data_source_path = state[Keys.PREPROCESSED_FILE_PATH]
    if not os.path.exists(data_source_path):
        raise FileNotFoundError(f"Preprocessed file not found: {data_source_path}")

    data_source_name = state[Keys.DATA_SOURCE_NAME]
    chat_name = state[Keys.CHAT_NAME]
    translation_dir = state[Keys.TRANSLATION_DIR]
    expected_file = state[Keys.EXPECTED_TRANSLATED_FILE]

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.TRANSLATE_MESSAGES, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "source_file": data_source_path}, metadata={"source_name": data_source_name}) as span:
        preprocessor = DataProcessorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=chat_name)

        settings = get_settings()
        force_refresh = state.get(Keys.FORCE_REFRESH_TRANSLATION, False)
        await preprocessor.preprocess_data(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, data_source_path=data_source_path, preprocessing_operations=[PreprocessingOperations.TRANSLATE_WHATSAPP_GROUP_CHAT_MESSAGES], output_dir=translation_dir, batch_size=settings.processing.translation_batch_size, skip_already_translated=True, chat_name=chat_name, data_source_name=data_source_name, force_refresh_translation=force_refresh)

        if not os.path.exists(expected_file):
            raise RuntimeError(f"Translation did not create expected file: {expected_file}")

        # Persisting messages to MongoDB with complete data (including translations)
        # Ensuring MongoDB has both original and translated content
        message_count = None
        try:
            with open(expected_file) as f:
                messages = json.load(f)
                message_count = len(messages) if isinstance(messages, list) else 0

                # Persisting messages to MongoDB (fail-soft) - async call
                mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
                if mongodb_run_id and isinstance(messages, list):
                    tracker = get_tracker()
                    stored_count = await tracker.store_messages(run_id=mongodb_run_id, chat_name=chat_name, data_source_name=data_source_name, messages=messages)
                    logger.info(f"Persisted {stored_count}/{message_count} TRANSLATED messages to MongoDB")
        except Exception as e:
            logger.warning(f"Failed to load/persist translated messages: {e}")

        result = {Keys.TRANSLATED_FILE_PATH: expected_file}

        # Updating span with output
        if span:
            span.update(output={"file_path": expected_file, "message_count": message_count})

        return result


@with_logging
@with_progress(STAGE_SEPARATE, start_message="Grouping messages into topical discussions...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.SEPARATE_DISCUSSIONS, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_SEPARATE_DISCUSSIONS_FILE, force_refresh_key=Keys.FORCE_REFRESH_SEPARATE_DISCUSSIONS, output_keys={Keys.SEPARATE_DISCUSSIONS_FILE_PATH: Keys.EXPECTED_SEPARATE_DISCUSSIONS_FILE})
async def separate_discussions(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Grouping messages into topical discussions using LLM.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_separate_discussions_file exists

    Fail-Fast Conditions:
    - OpenAI API errors
    - Input file not found
    - Invalid discussion structure returned by LLM

    Returns:
        dict: separate_discussions_file_path
    """
    data_source_path = state[Keys.TRANSLATED_FILE_PATH]
    if not os.path.exists(data_source_path):
        raise FileNotFoundError(f"Translated file not found: {data_source_path}")

    data_source_name = state[Keys.DATA_SOURCE_NAME]
    chat_name = state[Keys.CHAT_NAME]
    separate_discussions_dir = state[Keys.SEPARATE_DISCUSSIONS_DIR]
    expected_file = state[Keys.EXPECTED_SEPARATE_DISCUSSIONS_FILE]

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.SEPARATE_DISCUSSIONS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "source_file": data_source_path}, metadata={"source_name": data_source_name}) as span:
        preprocessor = DataProcessorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=chat_name)

        await preprocessor.preprocess_data(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, data_source_path=data_source_path, preprocessing_operations=[PreprocessingOperations.SEPARATE_WHATSAPP_GROUP_MESSAGE_DISCUSSIONS], output_dir=separate_discussions_dir)

        if not os.path.exists(expected_file):
            raise RuntimeError(f"Discussion separation did not create expected file: {expected_file}")

        # Counting discussions
        discussions_count = None
        try:
            with open(expected_file) as f:
                data = json.load(f)
                discussions = data.get(DiscussionKeys.DISCUSSIONS, []) if isinstance(data, dict) else data
                discussions_count = len(discussions) if isinstance(discussions, list) else 0
        except Exception as e:
            logger.warning(f"Failed to count discussions: {e}")

        result = {Keys.SEPARATE_DISCUSSIONS_FILE_PATH: expected_file}

        # Updating span with output
        if span:
            span.update(output={"discussions_count": discussions_count, "file_path": expected_file})

        return result


@with_logging
@with_progress(STAGE_RANK, start_message="Ranking discussions by relevance and quality...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.RANK_DISCUSSIONS, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_DISCUSSIONS_RANKING_FILE, force_refresh_key=Keys.FORCE_REFRESH_DISCUSSIONS_RANKING, output_keys={Keys.DISCUSSIONS_RANKING_FILE_PATH: Keys.EXPECTED_DISCUSSIONS_RANKING_FILE})
async def rank_discussions(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Ranking and categorizing discussions using the discussions_ranker subgraph.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_discussions_ranking_file exists

    The ranker considering:
    - Discussion relevance and importance
    - Technical depth and quality
    - Community engagement
    - Topical diversity
    - Recency and timeliness

    Fail-Fast Conditions:
    - Input file not found
    - Subgraph execution fails
    - Output file not created

    Returns:
        dict: discussions_ranking_file_path
    """
    discussions_file = state[Keys.SEPARATE_DISCUSSIONS_FILE_PATH]
    if not os.path.exists(discussions_file):
        raise FileNotFoundError(f"Discussions file not found: {discussions_file}")

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.RANK_DISCUSSIONS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": state[Keys.CHAT_NAME], "discussions_file": discussions_file}, metadata={"source_name": state.get(Keys.DATA_SOURCE_NAME)}) as span:
        # Creating subgraph state using helper function
        ranker_state = create_ranker_state_from_single_chat(state)

        # Invoking the discussions_ranker subgraph (async)
        result = await discussions_ranker_graph.ainvoke(ranker_state, config=config)
        expected_file = state[Keys.EXPECTED_DISCUSSIONS_RANKING_FILE]

        ranking_file_path = result.get(Keys.DISCUSSIONS_RANKING_FILE_PATH)
        if not ranking_file_path or not os.path.exists(ranking_file_path):
            raise RuntimeError(f"Discussions ranker did not create expected file: {expected_file}")

        # Counting ranked discussions
        featured_count = 0
        brief_count = 0

        # Persisting ranked discussions to MongoDB (fail-soft) - async call
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
        if mongodb_run_id:
            try:
                with open(ranking_file_path) as f:
                    ranked_discussions = json.load(f)

                # Extracting counts
                featured_count = len(ranked_discussions.get(RankingResultKeys.FEATURED_DISCUSSION_IDS, [])) if isinstance(ranked_discussions, dict) else 0
                brief_count = len(ranked_discussions.get(RankingResultKeys.BRIEF_MENTION_ITEMS, [])) if isinstance(ranked_discussions, dict) else 0

                tracker = get_tracker()
                chat_name = state[Keys.CHAT_NAME]
                stored_count = await tracker.store_discussions(run_id=mongodb_run_id, chat_name=chat_name, discussions=ranked_discussions if isinstance(ranked_discussions, list) else [])
                logger.info(f"Persisted {stored_count} discussions to MongoDB for chat: {chat_name}")
            except Exception as e:
                logger.warning(f"Failed to persist discussions to MongoDB: {e}")

        result_dict = {Keys.DISCUSSIONS_RANKING_FILE_PATH: ranking_file_path}

        # Updating span with output
        if span:
            span.update(output={"featured_count": featured_count, "brief_count": brief_count, "file_path": ranking_file_path})

        return result_dict


@with_logging
@with_progress(STAGE_GENERATE, start_message="Generating newsletter content...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.GENERATE_CONTENT, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_NEWSLETTER_JSON, force_refresh_key=Keys.FORCE_REFRESH_CONTENT, output_keys={Keys.NEWSLETTER_JSON_PATH: Keys.EXPECTED_NEWSLETTER_JSON, Keys.NEWSLETTER_MD_PATH: Keys.EXPECTED_NEWSLETTER_MD})
async def generate_content(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Generating newsletter summary from discussions using LLM.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_newsletter_json exists

    Using ranking output to:
    1. Filtering discussions to only include featured ones (top-K)
    2. Passing brief_mention one-liners for worth_mentioning section

    Fail-Fast Conditions:
    - OpenAI API errors
    - Input file not found
    - Missing ranking file or featured_discussion_ids
    - Invalid newsletter structure

    Returns:
        dict: newsletter_json_path, newsletter_md_path, newsletter_id
    """
    chat_name = state[Keys.CHAT_NAME]
    ranking_file = state.get(Keys.DISCUSSIONS_RANKING_FILE_PATH, "")
    data_source_path = state[Keys.SEPARATE_DISCUSSIONS_FILE_PATH]

    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.GENERATE_CONTENT, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "ranking_file": ranking_file}, metadata={"source_name": state.get(Keys.DATA_SOURCE_NAME)}) as span:
        # Step 1: Validating input files exist
        validate_ranking_file(ranking_file, chat_name)
        validate_discussions_file(data_source_path)

        # Step 2: Loading and validating ranking data
        featured_discussion_ids, brief_mention_items = load_ranking_data(ranking_file, chat_name)

        # Step 3: Loading and filtering discussions
        featured_discussions = load_featured_discussions(data_source_path, featured_discussion_ids, chat_name)

        # Step 3b: Load non-featured discussions as fallback for worth_mentioning
        non_featured_discussions = load_non_featured_discussions(data_source_path, featured_discussion_ids) if not brief_mention_items else []

        # Step 4: Extracting state values for content generation
        data_source_name = state[Keys.DATA_SOURCE_NAME]
        content_dir = state[Keys.CONTENT_DIR]
        summary_format = state[Keys.SUMMARY_FORMAT]
        start_date = state[Keys.START_DATE]
        end_date = state[Keys.END_DATE]
        desired_language = state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY]
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)

        # Step 5: Initializing MongoDB repository (async)
        newsletters_repo, newsletter_id = await initialize_mongodb_repository(mongodb_run_id, chat_name)

        # Step 6: Creating content generator and generating content
        content_generator = ContentGeneratorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=chat_name, summary_format=summary_format, newsletters_repo=newsletters_repo)

        date_str = start_date if start_date == end_date else f"{start_date} to {end_date}"
        featured_ids_for_generator = [d.get(DiscussionKeys.ID) for d in featured_discussions if d.get(DiscussionKeys.ID)]

        # Step 6b: Loading image-discussion map (optional, may be None)
        image_discussion_map = state.get(Keys.IMAGE_DISCUSSION_MAP)

        content_result = await content_generator.generate_content(
            operation=ContentGenerationOperations.GENERATE_NEWSLETTER_SUMMARY,
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            data_source_path=data_source_path,
            output_dir=content_dir,
            group_name=chat_name,
            date=date_str,
            featured_discussions=featured_discussions,
            brief_mention_items=brief_mention_items,
            non_featured_discussions=non_featured_discussions,
            desired_language_for_summary=desired_language,
            image_discussion_map=image_discussion_map,
            # MongoDB metadata for persistence
            newsletter_id=newsletter_id,
            run_id=mongodb_run_id,
            newsletter_type=NewsletterType.PER_CHAT,
            data_source_name=data_source_name,
            start_date=start_date,
            end_date=end_date,
            summary_format=summary_format,
            chat_name=chat_name,
            featured_discussion_ids=featured_ids_for_generator,
        )

        # Step 7: Extracting and validating output paths
        result_newsletter_id = content_result.get(ContentResultKeys.NEWSLETTER_ID) if content_result else None
        raw_json_path = content_result.get(RESULT_KEY_NEWSLETTER_SUMMARY_PATH) if content_result else None
        raw_md_path = content_result.get(RESULT_KEY_MARKDOWN_PATH) if content_result else None

        newsletter_json_path, newsletter_md_path = validate_content_generation_output(content_result=content_result, result_newsletter_id=result_newsletter_id, newsletter_json_path=raw_json_path, newsletter_md_path=raw_md_path, state=state)

        # Step 8: Loading newsletter for evaluation (async)
        newsletter_result = await load_newsletter_for_evaluation(result_newsletter_id, newsletters_repo, newsletter_json_path)

        # Step 9: Updating span with output metrics
        if span:
            span.update(output={"featured_count": len(featured_discussions), "brief_mention_count": len(brief_mention_items), "newsletter_json": newsletter_json_path, "newsletter_md": newsletter_md_path})

        # Step 10: Scoring newsletter structure (fail-soft)
        score_newsletter_if_available(span, newsletter_result, ctx.trace_id)

        # Step 11: Logging MongoDB persistence success
        log_mongodb_persistence_success(result_newsletter_id)

        # Extract HTML path from content result (generated alongside JSON/MD)
        newsletter_html_path = content_result.get(RESULT_KEY_HTML_PATH) if content_result else None

        return {Keys.NEWSLETTER_JSON_PATH: newsletter_json_path, Keys.NEWSLETTER_MD_PATH: newsletter_md_path, Keys.NEWSLETTER_HTML_PATH: newsletter_html_path, Keys.NEWSLETTER_ID: result_newsletter_id}


@with_logging
@with_progress(STAGE_ENRICH, start_message="Enriching newsletter with relevant links...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.ENRICH_WITH_LINKS, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
@with_cache_check(expected_file_key=Keys.EXPECTED_ENRICHED_NEWSLETTER_JSON, force_refresh_key=Keys.FORCE_REFRESH_LINK_ENRICHMENT, output_keys={Keys.ENRICHED_NEWSLETTER_JSON_PATH: Keys.EXPECTED_ENRICHED_NEWSLETTER_JSON, Keys.ENRICHED_NEWSLETTER_MD_PATH: Keys.EXPECTED_ENRICHED_NEWSLETTER_MD})
async def enrich_with_links(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Enriching newsletter content with relevant links using the link_enricher subgraph.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events
    - @with_cache_check: Skipping if expected_enriched_newsletter_json exists

    The subgraph:
    1. Extracting URLs from original discussion messages
    2. Searching web for relevant links based on discussion topics
    3. Aggregating and deduplicating links
    4. Using LLM to intelligently insert links into newsletter content

    Fail-Fast Conditions:
    - Input files not found
    - Subgraph execution fails
    - Output files not created

    Returns:
        dict: enriched_newsletter_json_path, enriched_newsletter_md_path
    """
    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.ENRICH_WITH_LINKS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": state[Keys.CHAT_NAME], "newsletter_file": state[Keys.NEWSLETTER_JSON_PATH]}, metadata={"source_name": state.get(Keys.DATA_SOURCE_NAME)}) as span:
        discussions_file = state[Keys.SEPARATE_DISCUSSIONS_FILE_PATH]
        newsletter_json_path = state[Keys.NEWSLETTER_JSON_PATH]

        if not os.path.exists(discussions_file):
            raise FileNotFoundError(f"Discussions file not found: {discussions_file}")
        if not os.path.exists(newsletter_json_path):
            raise FileNotFoundError(f"Newsletter JSON file not found: {newsletter_json_path}")

        # Creating subgraph state using helper function
        enricher_state = create_enricher_state_from_single_chat(state)

        # Invoking the link_enricher subgraph (async)
        result = await link_enricher_graph.ainvoke(enricher_state, config=config)
        expected_enriched_json = state[Keys.EXPECTED_ENRICHED_NEWSLETTER_JSON]
        expected_enriched_md = state[Keys.EXPECTED_ENRICHED_NEWSLETTER_MD]

        enriched_json_path = result.get(Keys.ENRICHED_NEWSLETTER_JSON_PATH)
        enriched_md_path = result.get(Keys.ENRICHED_NEWSLETTER_MD_PATH)

        if not enriched_json_path or not os.path.exists(enriched_json_path):
            raise RuntimeError(f"Link enricher did not create expected JSON file: {expected_enriched_json}")
        if not enriched_md_path or not os.path.exists(enriched_md_path):
            raise RuntimeError(f"Link enricher did not create expected MD file: {expected_enriched_md}")

        # Updating span with output metrics
        if span:
            span.update(output={"enriched_json": enriched_json_path, "enriched_md": enriched_md_path, "files_exist": os.path.exists(enriched_json_path) and os.path.exists(enriched_md_path)})

        # Storing enriched newsletter to MongoDB (async)
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
        if mongodb_run_id:
            import re

            chat_slug = re.sub(r"[^a-z0-9]+", "_", state[Keys.CHAT_NAME].lower()).strip("_")
            newsletter_id = f"{mongodb_run_id}_nl_{chat_slug}"

            # Extracting links_added from result if available
            links_added = result.get(ContentResultKeys.LINKS_ADDED, 0)
            stats = {ContentResultKeys.LINKS_ADDED: links_added}

            tracker = get_tracker()
            await tracker.store_newsletter(newsletter_id=newsletter_id, run_id=mongodb_run_id, newsletter_type=NewsletterType.PER_CHAT, data_source_name=state[Keys.DATA_SOURCE_NAME], chat_name=state[Keys.CHAT_NAME], start_date=state[Keys.START_DATE], end_date=state[Keys.END_DATE], summary_format=state[Keys.SUMMARY_FORMAT], desired_language=state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY], json_path=enriched_json_path, md_path=enriched_md_path, stats=stats, version_type=NewsletterVersionType.ENRICHED)

        return {Keys.ENRICHED_NEWSLETTER_JSON_PATH: enriched_json_path, Keys.ENRICHED_NEWSLETTER_MD_PATH: enriched_md_path}


@with_logging
@with_progress(STAGE_TRANSLATE_FINAL, start_message="Translating newsletter to target language...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.TRANSLATE_FINAL_SUMMARY, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
async def translate_final_summary(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Translating newsletter summary to desired language.

    Decorators handling:
    - @with_logging: Logging entry/exit with duration
    - @with_progress: Sending SSE progress events

    Note: Does NOT use @with_cache_check because of special English skip logic.

    Behavior:
    - If desired_language_for_summary == "english": Skipping translation, returning None
    - If desired_language_for_summary != "english": Translating to target language

    Fail-Fast Conditions:
    - OpenAI API errors
    - Input file not found
    - Invalid translation format

    Returns:
        dict: final_translated_file_path (None if English, otherwise path to translated file)
    """
    # Setting up Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.SingleChatAnalyzer.TRANSLATE_FINAL_SUMMARY, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": state[Keys.CHAT_NAME], "desired_language": state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY], "source_file": state.get(Keys.ENRICHED_NEWSLETTER_MD_PATH)}, metadata={"source_name": state.get(Keys.DATA_SOURCE_NAME)}) as span:
        desired_language = state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY]

        # Skipping if already in English
        if desired_language.lower() == DEFAULT_LANGUAGE:
            if span:
                span.update(output={"skipped": True, "reason": "already_english"})
            return {Keys.FINAL_TRANSLATED_FILE_PATH: None}

        expected_file = state[Keys.EXPECTED_FINAL_TRANSLATED_FILE]
        force_refresh = state.get(Keys.FORCE_REFRESH_FINAL_TRANSLATION, False)

        # Checking for existing file (custom cache check)
        if not force_refresh and os.path.exists(expected_file):
            if span:
                span.update(output={"file_path": expected_file, "reused_existing": True})
            return {Keys.FINAL_TRANSLATED_FILE_PATH: expected_file}

        # Translating summary (using ENRICHED newsletter)
        data_source_path = state[Keys.ENRICHED_NEWSLETTER_MD_PATH]
        if not os.path.exists(data_source_path):
            raise FileNotFoundError(f"Enriched Newsletter Markdown file not found: {data_source_path}")

        data_source_name = state[Keys.DATA_SOURCE_NAME]
        chat_name = state[Keys.CHAT_NAME]
        summary_format = state[Keys.SUMMARY_FORMAT]
        start_date = state[Keys.START_DATE]
        end_date = state[Keys.END_DATE]

        content_generator = ContentGeneratorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=chat_name, summary_format=summary_format)

        date_str = start_date if start_date == end_date else f"{start_date} to {end_date}"

        await content_generator.generate_content(operation=ContentGenerationOperations.TRANSLATE_SUMMARY, data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, data_source_path=data_source_path, group_name=chat_name, expected_final_translated_file_path=expected_file, date=date_str, desired_language_for_summary=desired_language)

        if not os.path.exists(expected_file):
            raise RuntimeError(f"Translation did not create expected file: {expected_file}")

        # Updating span with output
        if span:
            span.update(output={"file_path": expected_file, "target_language": desired_language, "reused_existing": False})

        # Storing translated newsletter to MongoDB (async)
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
        if mongodb_run_id and expected_file:  # Only if translation was performed
            import re

            chat_slug = re.sub(r"[^a-z0-9]+", "_", state[Keys.CHAT_NAME].lower()).strip("_")
            newsletter_id = f"{mongodb_run_id}_nl_{chat_slug}"

            tracker = get_tracker()
            await tracker.store_newsletter(
                newsletter_id=newsletter_id,
                run_id=mongodb_run_id,
                newsletter_type=NewsletterType.PER_CHAT,
                data_source_name=state[Keys.DATA_SOURCE_NAME],
                chat_name=state[Keys.CHAT_NAME],
                start_date=state[Keys.START_DATE],
                end_date=state[Keys.END_DATE],
                summary_format=state[Keys.SUMMARY_FORMAT],
                desired_language=state[Keys.DESIRED_LANGUAGE_FOR_SUMMARY],
                json_path="",  # Not applicable for translated version
                md_path=expected_file,
                version_type=NewsletterVersionType.TRANSLATED,
            )

        return {Keys.FINAL_TRANSLATED_FILE_PATH: expected_file}


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================


def build_newsletter_generation_graph() -> StateGraph:
    """
    Building and compiling the newsletter generation workflow graph.

    Graph Structure:
    START → setup_directories → extract_messages → slm_prefilter → extract_images →
    preprocess_messages → translate_messages → separate_discussions → slm_enrichment →
    rank_discussions → generate_content → enrich_with_links → translate_final_summary → END

    Note: Session validation (ensure_valid_session) now running once at orchestrator level
    (parallel_orchestrator.py) before workers are dispatched, preventing rate limiting
    from parallel login attempts.

    SLM pre-filter is optional and controlled by SLM_ENABLED config.
    If disabled or unavailable, the node passes through without modification (fail-soft).

    Returns:
        Compiled StateGraph with checkpointing enabled
    """
    logger.info("Building newsletter generation graph...")

    # Creating graph builder
    builder = StateGraph(SingleChatState)

    # Adding nodes
    # NOTE: ensure_valid_session now running once at orchestrator level (parallel_orchestrator.py)
    # to avoid parallel login attempts that cause rate limiting
    builder.add_node(NodeNames.SingleChatAnalyzer.SETUP_DIRECTORIES, setup_directories)
    builder.add_node(NodeNames.SingleChatAnalyzer.EXTRACT_MESSAGES, extract_messages)
    builder.add_node(NodeNames.SingleChatAnalyzer.SLM_PREFILTER, slm_prefilter_node)  # SLM pre-filtering (optional, controlled by SLM_ENABLED)
    builder.add_node(NodeNames.SingleChatAnalyzer.EXTRACT_IMAGES, extract_images_node)  # Image extraction (optional, controlled by VISION_ENABLED)
    builder.add_node(NodeNames.SingleChatAnalyzer.PREPROCESS_MESSAGES, preprocess_messages)
    builder.add_node(NodeNames.SingleChatAnalyzer.TRANSLATE_MESSAGES, translate_messages)
    builder.add_node(NodeNames.SingleChatAnalyzer.SEPARATE_DISCUSSIONS, separate_discussions)
    builder.add_node(NodeNames.SingleChatAnalyzer.SLM_ENRICHMENT, slm_enrichment_node)  # SLM multi-label enrichment (optional, controlled by SLM_ENRICHMENT_ENABLED)
    builder.add_node(NodeNames.SingleChatAnalyzer.RANK_DISCUSSIONS, rank_discussions)
    builder.add_node(NodeNames.SingleChatAnalyzer.ASSOCIATE_IMAGES, associate_images_node)
    builder.add_node(NodeNames.SingleChatAnalyzer.GENERATE_CONTENT, generate_content)
    builder.add_node(NodeNames.SingleChatAnalyzer.ENRICH_WITH_LINKS, enrich_with_links)
    builder.add_node(NodeNames.SingleChatAnalyzer.TRANSLATE_FINAL_SUMMARY, translate_final_summary)

    # Defining linear flow
    # NOTE: Session validation now happening once at orchestrator level before workers start
    builder.add_edge(START, NodeNames.SingleChatAnalyzer.SETUP_DIRECTORIES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.SETUP_DIRECTORIES, NodeNames.SingleChatAnalyzer.EXTRACT_MESSAGES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.EXTRACT_MESSAGES, NodeNames.SingleChatAnalyzer.SLM_PREFILTER)  # SLM pre-filter after extraction
    builder.add_edge(NodeNames.SingleChatAnalyzer.SLM_PREFILTER, NodeNames.SingleChatAnalyzer.EXTRACT_IMAGES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.EXTRACT_IMAGES, NodeNames.SingleChatAnalyzer.PREPROCESS_MESSAGES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.PREPROCESS_MESSAGES, NodeNames.SingleChatAnalyzer.TRANSLATE_MESSAGES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.TRANSLATE_MESSAGES, NodeNames.SingleChatAnalyzer.SEPARATE_DISCUSSIONS)
    builder.add_edge(NodeNames.SingleChatAnalyzer.SEPARATE_DISCUSSIONS, NodeNames.SingleChatAnalyzer.SLM_ENRICHMENT)
    builder.add_edge(NodeNames.SingleChatAnalyzer.SLM_ENRICHMENT, NodeNames.SingleChatAnalyzer.RANK_DISCUSSIONS)
    builder.add_edge(NodeNames.SingleChatAnalyzer.RANK_DISCUSSIONS, NodeNames.SingleChatAnalyzer.ASSOCIATE_IMAGES)
    builder.add_edge(NodeNames.SingleChatAnalyzer.ASSOCIATE_IMAGES, NodeNames.SingleChatAnalyzer.GENERATE_CONTENT)
    builder.add_edge(NodeNames.SingleChatAnalyzer.GENERATE_CONTENT, NodeNames.SingleChatAnalyzer.ENRICH_WITH_LINKS)
    builder.add_edge(NodeNames.SingleChatAnalyzer.ENRICH_WITH_LINKS, NodeNames.SingleChatAnalyzer.TRANSLATE_FINAL_SUMMARY)
    builder.add_edge(NodeNames.SingleChatAnalyzer.TRANSLATE_FINAL_SUMMARY, END)

    compiled_graph = builder.compile()

    logger.info("Newsletter generation graph compiled successfully")

    return compiled_graph


# Creating and exporting the compiled graph
newsletter_generation_graph = build_newsletter_generation_graph()
