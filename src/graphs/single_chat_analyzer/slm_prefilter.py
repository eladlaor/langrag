"""
SLM Message Pre-filter Node

Filters low-quality messages using local SLM before expensive LLM processing.
This node reduces API costs by 15-30% by filtering spam, greetings, and
off-topic messages early in the pipeline.

Design:
- Fail-soft: If SLM is unavailable, skip filtering and continue pipeline
- Fail-safe: UNCERTAIN messages continue to LLM (don't filter important content)
- Optional: Controlled by SLM_ENABLED environment variable

Configuration:
- SLM_ENABLED: Set to "true" to enable (default: false)
- SLM_MODEL: Ollama model to use for classification
- SLM_CONFIDENCE_THRESHOLD: Minimum confidence for classification
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from api.sse import STAGE_PREPROCESS, with_logging, with_progress
from config import get_settings
from constants import NodeNames, WORKFLOW_NAME_NEWSLETTER_GENERATION, DIAGNOSTIC_CATEGORY_SLM_FILTER, UNKNOWN_CHAT_NAME
from core.slm import MessageClassifier, get_slm_provider
from core.slm.classifier import (
    convert_raw_messages_to_classification_input,
    filter_messages_by_classification,
)
from custom_types.slm_schemas import SLMFilterStats
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.state_keys import SingleChatStateKeys as Keys
from observability import extract_trace_context, langfuse_span
from observability.metrics import with_metrics
from utils.run_diagnostics import get_diagnostics

logger = logging.getLogger(__name__)


async def _persist_raw_messages_to_mongodb(
    mongodb_run_id: str | None,
    chat_name: str,
    data_source_name: str,
    messages: list[dict],
    classification_map: dict[str, dict] | None = None,
) -> None:
    """
    Persist all raw messages to MongoDB with optional SLM classification metadata.

    Fail-soft: logs warnings on failure but does not raise.
    """
    if not mongodb_run_id:
        return

    try:
        from db.run_tracker import get_tracker

        tracker = get_tracker()
        count = await tracker.store_raw_messages(
            run_id=mongodb_run_id,
            chat_name=chat_name,
            data_source_name=data_source_name,
            messages=messages,
            classification_map=classification_map,
        )
        logger.info(f"Persisted {count}/{len(messages)} raw messages to MongoDB for chat {chat_name}")
    except Exception as e:
        logger.warning(f"Failed to persist raw messages to MongoDB: {e}")


def _atomic_json_write(file_path: str, data: Any) -> None:
    """
    Write JSON data atomically using temp file and rename.

    This prevents data corruption if the process is interrupted during write.

    Args:
        file_path: Destination file path
        data: Data to serialize as JSON
    """
    path = Path(file_path)
    temp_fd, temp_path = tempfile.mkstemp(suffix=path.suffix, prefix=f"{path.stem}_tmp_", dir=path.parent)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Atomic rename
        os.replace(temp_path, file_path)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


@with_logging
@with_progress(STAGE_PREPROCESS, start_message="Pre-filtering messages with SLM...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.SLM_PREFILTER, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
async def slm_prefilter_node(state: SingleChatState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Filter low-quality messages using SLM before LLM processing.

    This node runs after extraction and before preprocessing, filtering out
    spam, greetings, and low-value messages to reduce downstream API costs.

    Behavior:
    - If SLM_ENABLED=false: Skip filtering, return empty update
    - If SLM unavailable: Skip filtering (fail-soft), log info
    - If SLM available: Classify and filter messages, update extracted file

    The node persists ALL messages to MongoDB before filtering, then modifies
    the extracted messages file in-place with only the filtered subset.

    Args:
        state: Current workflow state with extracted_file_path
        config: LangGraph runnable config

    Returns:
        State update with:
        - slm_filter_stats: Filter statistics as dict
        - message_count: Updated message count after filtering (if filtering occurred)
    """
    settings = get_settings()

    # Check if SLM filtering is enabled
    if not settings.slm.enabled:
        logger.info("SLM filtering disabled (SLM_ENABLED=false), skipping")

        # Persist all raw messages to MongoDB even when SLM is disabled
        mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)
        extracted_file_path = state.get(Keys.EXTRACTED_FILE_PATH)
        if mongodb_run_id and extracted_file_path and os.path.exists(extracted_file_path):
            try:
                with open(extracted_file_path, encoding="utf-8") as f:
                    messages = json.load(f)
                if isinstance(messages, list):
                    await _persist_raw_messages_to_mongodb(
                        mongodb_run_id=mongodb_run_id,
                        chat_name=state.get(Keys.CHAT_NAME, UNKNOWN_CHAT_NAME),
                        data_source_name=state.get(Keys.DATA_SOURCE_NAME, ""),
                        messages=messages,
                        classification_map=None,
                    )
            except Exception as e:
                logger.warning(f"Failed to load messages for MongoDB persistence (SLM disabled): {e}")

        return {
            "slm_filter_stats": SLMFilterStats(enabled=False).model_dump(),
        }

    extracted_file_path = state.get(Keys.EXTRACTED_FILE_PATH)
    if not extracted_file_path:
        logger.warning("No extracted_file_path in state, skipping SLM filter")
        return {
            "slm_filter_stats": SLMFilterStats(
                enabled=True,
                fallback_used=True,
            ).model_dump(),
        }

    if not os.path.exists(extracted_file_path):
        logger.warning(f"Extracted file not found: {extracted_file_path}, skipping SLM filter")
        return {
            "slm_filter_stats": SLMFilterStats(
                enabled=True,
                fallback_used=True,
            ).model_dump(),
        }

    chat_name = state.get(Keys.CHAT_NAME, UNKNOWN_CHAT_NAME)
    mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)

    # Setup Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name="slm_prefilter", trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": chat_name, "file_path": extracted_file_path}, metadata={"model": settings.slm.model}) as span:
        try:
            # Load extracted messages
            with open(extracted_file_path, encoding="utf-8") as f:
                messages = json.load(f)

            if not isinstance(messages, list):
                logger.warning(f"Extracted messages not a list (got {type(messages).__name__}), " "skipping SLM filter")
                return {
                    "slm_filter_stats": SLMFilterStats(
                        enabled=True,
                        fallback_used=True,
                    ).model_dump(),
                }

            original_count = len(messages)
            logger.info(f"SLM pre-filter processing {original_count} messages " f"for chat_name={chat_name}")

            # Check SLM availability, auto-pull model if needed
            provider = get_slm_provider()
            health = await provider.health_check()

            # If Ollama is reachable but model not loaded, attempt auto-pull
            if health.available and not health.model_loaded:
                logger.info(f"SLM model not loaded, attempting auto-pull for chat_name={chat_name}...")
                model_ready = await provider.ensure_model_loaded()
                if model_ready:
                    health = await provider.health_check()
                    logger.info(f"SLM model auto-pulled successfully: {health.model_name}")
                else:
                    logger.error(f"Failed to auto-pull SLM model '{settings.slm.model}'. " "Cannot proceed with SLM filtering.")

            if not health.available or not health.model_loaded:
                logger.info(f"SLM not available (available={health.available}, " f"model_loaded={health.model_loaded}): {health.error_message}. " "Skipping filter (fail-soft).")
                stats = SLMFilterStats(
                    enabled=True,
                    total_input_messages=original_count,
                    total_output_messages=original_count,
                    slm_available=False,
                    fallback_used=True,
                )

                # Persist all raw messages to MongoDB (no classification data)
                await _persist_raw_messages_to_mongodb(
                    mongodb_run_id=mongodb_run_id,
                    chat_name=chat_name,
                    data_source_name=state.get(Keys.DATA_SOURCE_NAME, ""),
                    messages=messages,
                    classification_map=None,
                )

                # Emit diagnostic if run is tracked
                if mongodb_run_id:
                    diagnostics = get_diagnostics(mongodb_run_id)
                    diagnostics.info(category=DIAGNOSTIC_CATEGORY_SLM_FILTER, message=f"SLM service unavailable, continuing without filtering: {health.error_message}", node_name="slm_prefilter", details={"health_status": health.model_dump()})
                else:
                    logger.debug("No mongodb_run_id, skipping diagnostic emission")

                if span:
                    span.update(output={"skipped": True, "reason": "slm_unavailable"})

                return {"slm_filter_stats": stats.model_dump()}

            # Convert messages to classification input
            classification_input = convert_raw_messages_to_classification_input(
                messages,
                include_context=True,
            )

            # Classify messages
            classifier = MessageClassifier(provider=provider)
            classification_results = await classifier.classify_batch(classification_input)

            # Filter messages
            filtered_messages, stats = filter_messages_by_classification(
                messages,
                classification_results,
            )
            stats.model_used = health.model_name

            # Build classification_map for MongoDB persistence
            classification_map = {}
            for r in classification_results.results:
                if r.message_id:
                    classification_map[r.message_id] = {
                        "classification": str(r.classification),
                        "confidence": r.confidence,
                        "reason": r.reason,
                    }

            # Persist ALL raw messages to MongoDB with SLM classification metadata
            await _persist_raw_messages_to_mongodb(
                mongodb_run_id=mongodb_run_id,
                chat_name=chat_name,
                data_source_name=state.get(Keys.DATA_SOURCE_NAME, ""),
                messages=messages,
                classification_map=classification_map,
            )

            # Write filtered messages atomically (pipeline still needs filtered file)
            _atomic_json_write(extracted_file_path, filtered_messages)

            logger.info(f"SLM filter for chat_name={chat_name}: " f"{original_count} → {len(filtered_messages)} messages " f"({stats.filter_rate:.1f}% filtered, model={stats.model_used})")

            # Emit diagnostic if significant filtering occurred
            if mongodb_run_id and stats.filter_rate > 20:
                diagnostics = get_diagnostics(mongodb_run_id)
                diagnostics.info(
                    category=DIAGNOSTIC_CATEGORY_SLM_FILTER,
                    message=f"SLM filtered {stats.filter_rate:.1f}% of messages",
                    node_name="slm_prefilter",
                    details={
                        "kept": stats.kept,
                        "filtered": stats.filtered,
                        "uncertain": stats.uncertain,
                        "model": stats.model_used,
                    },
                )

            # Update span with results
            if span:
                span.update(
                    output={
                        "original_count": original_count,
                        "filtered_count": len(filtered_messages),
                        "filter_rate": stats.filter_rate,
                        "model": stats.model_used,
                        "processing_time_ms": stats.processing_time_ms,
                    }
                )

            return {
                "slm_filter_stats": stats.model_dump(),
                "message_count": len(filtered_messages),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extracted messages JSON: {e}, " f"file_path={extracted_file_path}", exc_info=True)
            # Fail-soft: continue without filtering
            stats = SLMFilterStats(enabled=True, fallback_used=True)
            if span:
                span.update(output={"error": f"JSON parse error: {e}", "fallback_used": True})
            return {"slm_filter_stats": stats.model_dump()}

        except Exception as e:
            logger.error(f"SLM pre-filter failed: {e}, chat_name={chat_name}", exc_info=True)

            # Fail-soft: don't block pipeline, continue without filtering
            stats = SLMFilterStats(enabled=True, fallback_used=True)

            if span:
                span.update(output={"error": str(e), "fallback_used": True})

            # Emit diagnostic if run is tracked
            if mongodb_run_id:
                diagnostics = get_diagnostics(mongodb_run_id)
                diagnostics.error(category=DIAGNOSTIC_CATEGORY_SLM_FILTER, message=f"SLM filter failed, continuing without filtering: {e}", node_name="slm_prefilter", details={"error": str(e)})

            return {"slm_filter_stats": stats.model_dump()}
