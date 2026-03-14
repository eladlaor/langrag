"""
Node Decorators for LangGraph Workflows

These decorators reduce boilerplate in graph nodes by extracting common
patterns: cache checking, progress emission, and logging.

All decorators support both sync and async functions for LangGraph 1.0 compatibility.
"""

import asyncio
import logging
import os
import time
from functools import wraps
from typing import Any
from collections.abc import Callable

from custom_types.sse_events import create_stage_event
from constants import PipelineStage, ProgressEventType, StageStatus, CONSOLIDATED_CHAT_SENTINEL, UNKNOWN_CHAT_NAME
from graphs.state_keys import SingleChatStateKeys as Keys
from .progress_queue import get_progress_queue

logger = logging.getLogger(__name__)


def with_cache_check(
    expected_file_key: str,
    force_refresh_key: str,
    output_keys: dict[str, str],
):
    """
    Decorator: Skip execution if cached file exists.

    This decorator checks for existing output files before running the node.
    If the cache is valid (file exists and force_refresh is False), the node
    is skipped and cached paths are returned.

    Supports both sync and async functions (dual-mode for LangGraph 1.0 migration).

    Args:
        expected_file_key: State key for expected output file path
        force_refresh_key: State key for force refresh flag
        output_keys: Mapping of {output_state_key: source_state_key_for_cached_value}

    Usage:
        @with_cache_check(
            expected_file_key="expected_extracted_file",
            force_refresh_key="force_refresh_extraction",
            output_keys={"extracted_file_path": "expected_extracted_file"}
        )
        def extract_messages(state):
            # Only runs if cache miss
            ...

        # Also works with async functions:
        @with_cache_check(...)
        async def extract_messages(state):
            ...
    """

    def decorator(func: Callable) -> Callable:
        def _check_cache(state: dict[str, Any]) -> dict[str, Any] | None:
            """Common cache check logic for sync and async."""
            expected_file = state.get(expected_file_key)
            force_refresh = state.get(force_refresh_key, False)

            if not force_refresh and expected_file and os.path.exists(expected_file):
                logger.info(f"[{func.__name__}] Cache hit: {expected_file}")
                result = {"reused_existing": True}
                for output_key, source_key in output_keys.items():
                    result[output_key] = state.get(source_key)
                return result
            return None

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
                cached = _check_cache(state)
                if cached is not None:
                    return cached
                return await func(state, config)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
                cached = _check_cache(state)
                if cached is not None:
                    return cached
                return func(state, config)

            return sync_wrapper

    return decorator


def with_progress(
    stage: str,
    start_message: str | None = None,
    success_message: str | None = None,
):
    """
    Decorator: Emit progress events automatically.

    This decorator wraps node functions to automatically emit SSE progress
    events for start, completion, and failure states.

    Supports both sync and async functions (dual-mode for LangGraph 1.0 migration).

    Args:
        stage: Stage constant (STAGE_EXTRACT, STAGE_PREPROCESS, etc.)
        start_message: Custom in_progress message (optional)
        success_message: Custom completed message (optional)

    Usage:
        @with_progress(STAGE_EXTRACT, start_message="Extracting messages...")
        def extract_messages(state):
            ...

        # Also works with async functions:
        @with_progress(STAGE_EXTRACT, start_message="Extracting messages...")
        async def extract_messages(state):
            ...
    """

    def decorator(func: Callable) -> Callable:
        def _get_progress_context(state: dict[str, Any]):
            """Extract progress context from state.

            For consolidation nodes (no chat_name), uses '__consolidated__' as special identifier.
            Frontend detects this and displays in separate consolidation progress section.
            """
            # Consolidation stages use special identifier
            CONSOLIDATION_STAGES = [
                PipelineStage.SETUP_CONSOLIDATED_DIRECTORIES,
                PipelineStage.CONSOLIDATE_DISCUSSIONS,
                PipelineStage.RANK_CONSOLIDATED_DISCUSSIONS,
                PipelineStage.GENERATE_CONSOLIDATED_NEWSLETTER,
                PipelineStage.ENRICH_CONSOLIDATED_NEWSLETTER,
                PipelineStage.TRANSLATE_CONSOLIDATED_NEWSLETTER,
            ]

            if stage in CONSOLIDATION_STAGES:
                chat_name = CONSOLIDATED_CHAT_SENTINEL
            else:
                chat_name = state.get(Keys.CHAT_NAME, UNKNOWN_CHAT_NAME)

            thread_id = state.get(Keys.PROGRESS_THREAD_ID)
            progress = None

            if thread_id:
                try:
                    progress = get_progress_queue(thread_id)
                except Exception as e:
                    logger.warning(f"Failed to get progress queue: {e}")

            return chat_name, progress

        def _emit_start(chat_name: str, progress):
            """Emit in_progress event."""
            if progress:
                msg = start_message or f"Processing {stage}..."
                progress.emit(ProgressEventType.STAGE_PROGRESS, create_stage_event(chat_name=chat_name, stage=stage, status=StageStatus.IN_PROGRESS, message=msg))

        def _emit_completed(chat_name: str, progress, result: dict[str, Any], duration: float):
            """Emit completed event."""
            if progress:
                msg = success_message or f"Completed {stage}"
                # Extract output file from result for progress event
                output_file = None
                output_file_keys = [
                    Keys.EXTRACTED_FILE_PATH,
                    Keys.PREPROCESSED_FILE_PATH,
                    Keys.TRANSLATED_FILE_PATH,
                    Keys.SEPARATE_DISCUSSIONS_FILE_PATH,
                    Keys.DISCUSSIONS_RANKING_FILE_PATH,
                    Keys.NEWSLETTER_MD_PATH,
                    Keys.ENRICHED_NEWSLETTER_MD_PATH,
                    Keys.FINAL_TRANSLATED_FILE_PATH,
                ]
                for key in output_file_keys:
                    if key in result:
                        output_file = result[key]
                        break

                progress.emit(ProgressEventType.STAGE_PROGRESS, create_stage_event(chat_name=chat_name, stage=stage, status=StageStatus.COMPLETED, message=msg, output_file=output_file, metadata={"duration_s": round(duration, 2)}))

        def _emit_failed(chat_name: str, progress, error: Exception):
            """Emit failed event."""
            if progress:
                progress.emit(ProgressEventType.STAGE_PROGRESS, create_stage_event(chat_name=chat_name, stage=stage, status=StageStatus.FAILED, message=f"{stage} failed: {str(error)}"))

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
                chat_name, progress = _get_progress_context(state)
                _emit_start(chat_name, progress)
                start_time = time.time()

                try:
                    result = await func(state, config)
                    duration = time.time() - start_time
                    _emit_completed(chat_name, progress, result, duration)
                    return result

                except Exception as e:
                    _emit_failed(chat_name, progress, e)
                    raise

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
                chat_name, progress = _get_progress_context(state)
                _emit_start(chat_name, progress)
                start_time = time.time()

                try:
                    result = func(state, config)
                    duration = time.time() - start_time
                    _emit_completed(chat_name, progress, result, duration)
                    return result

                except Exception as e:
                    _emit_failed(chat_name, progress, e)
                    raise

            return sync_wrapper

    return decorator


def with_logging(func: Callable) -> Callable:
    """
    Decorator: Log node entry/exit with duration.

    This decorator adds structured logging for node execution,
    including start time, duration, and output keys.

    Supports both sync and async functions (dual-mode for LangGraph 1.0 migration).

    Usage:
        @with_logging
        def extract_messages(state):
            ...

        # Also works with async functions:
        @with_logging
        async def extract_messages(state):
            ...
    """
    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
            chat_name = state.get(Keys.CHAT_NAME, UNKNOWN_CHAT_NAME)
            logger.info(f"[{func.__name__}] START chat={chat_name}")
            start_time = time.time()

            try:
                result = await func(state, config)
                duration = time.time() - start_time
                keys_changed = list(result.keys()) if result else []
                logger.info(f"[{func.__name__}] END duration={duration:.2f}s keys={keys_changed}")
                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"[{func.__name__}] FAILED duration={duration:.2f}s error={e}")
                raise

        return async_wrapper
    else:

        @wraps(func)
        def sync_wrapper(state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
            chat_name = state.get(Keys.CHAT_NAME, UNKNOWN_CHAT_NAME)
            logger.info(f"[{func.__name__}] START chat={chat_name}")
            start_time = time.time()

            try:
                result = func(state, config)
                duration = time.time() - start_time
                keys_changed = list(result.keys()) if result else []
                logger.info(f"[{func.__name__}] END duration={duration:.2f}s keys={keys_changed}")
                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"[{func.__name__}] FAILED duration={duration:.2f}s error={e}")
                raise

        return sync_wrapper


def pipeline_node(
    stage: str,
    cache_file_key: str | None = None,
    force_refresh_key: str | None = None,
    output_key: str | None = None,
    start_message: str | None = None,
    success_message: str | None = None,
):
    """
    Composed decorator for standard pipeline nodes.

    Combines cache checking, progress tracking, and logging into a single
    decorator for cleaner node definitions. This reduces decorator stacking
    from 3 decorators to 1.

    Supports both sync and async functions (dual-mode for LangGraph 1.0 migration).
    Each inner decorator auto-detects async functions and preserves async nature
    through the decorator chain.

    Args:
        stage: Stage constant (STAGE_EXTRACT, STAGE_PREPROCESS, etc.)
        cache_file_key: State key for expected output file (enables caching)
        force_refresh_key: State key for force refresh flag
        output_key: Output state key to populate from cache
        start_message: Custom in_progress message (optional)
        success_message: Custom completed message (optional)

    Usage (sync, with caching):
        @pipeline_node(
            stage=STAGE_EXTRACT,
            cache_file_key="expected_extracted_file",
            force_refresh_key="force_refresh_extraction",
            output_key="extracted_file_path",
            start_message="Extracting messages..."
        )
        def extract_messages(state):
            ...

    Usage (async, without caching):
        @pipeline_node(
            stage=STAGE_RANK,
            start_message="Ranking discussions..."
        )
        async def rank_discussions(state):
            ...

    Equivalent to stacking (in reverse order):
        @with_cache_check(...)  # Outermost - runs first
        @with_progress(...)
        @with_logging           # Innermost - wraps actual function
        def node(state): ...
    """

    def decorator(func: Callable) -> Callable:
        # Start with the base function
        wrapped = func

        # Apply logging (innermost decorator) - auto-detects async
        wrapped = with_logging(wrapped)

        # Apply progress tracking - auto-detects async
        wrapped = with_progress(stage=stage, start_message=start_message, success_message=success_message)(wrapped)

        # Apply cache checking if configured (outermost decorator) - auto-detects async
        if cache_file_key and force_refresh_key and output_key:
            wrapped = with_cache_check(expected_file_key=cache_file_key, force_refresh_key=force_refresh_key, output_keys={output_key: cache_file_key})(wrapped)

        # Preserve function metadata
        wrapped = wraps(func)(wrapped)

        return wrapped

    return decorator
