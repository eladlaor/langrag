"""
Helper functions for generate_content node.

Extracted from the main graph.py to reduce complexity and improve testability.
Each helper handles a specific concern:
- Input validation and data loading
- MongoDB repository initialization
- Output validation
- Newsletter loading for evaluation
- Evaluation scoring
"""

import json
import logging
import os
import re
from typing import Any

from config import get_settings
from graphs.state_keys import SingleChatStateKeys as Keys
from custom_types.field_keys import DiscussionKeys, RankingResultKeys
from observability import score_newsletter_structure

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT VALIDATION HELPERS
# =============================================================================


def validate_ranking_file(ranking_file: str, chat_name: str) -> None:
    """
    Validate that the ranking file exists.

    Args:
        ranking_file: Path to the discussions ranking file
        chat_name: Name of the chat (for error messages)

    Raises:
        RuntimeError: If ranking_file path is empty
        FileNotFoundError: If ranking file doesn't exist
    """
    try:
        if not ranking_file:
            raise RuntimeError(f"Missing discussions_ranking_file_path in state for chat '{chat_name}'. " "The rank_discussions node must run before generate_content.")
        if not os.path.exists(ranking_file):
            raise FileNotFoundError(f"Discussions ranking file not found: {ranking_file}")
    except (RuntimeError, FileNotFoundError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating ranking file: {e}, chat_name={chat_name}, ranking_file={ranking_file}")
        raise RuntimeError(f"Failed to validate ranking file: {e}") from e


def validate_discussions_file(data_source_path: str) -> None:
    """
    Validate that the discussions file exists.

    Args:
        data_source_path: Path to the separated discussions file

    Raises:
        FileNotFoundError: If discussions file doesn't exist
    """
    try:
        if not os.path.exists(data_source_path):
            raise FileNotFoundError(f"Discussions file not found: {data_source_path}")
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating discussions file: {e}, data_source_path={data_source_path}")
        raise RuntimeError(f"Failed to validate discussions file: {e}") from e


def load_ranking_data(ranking_file: str, chat_name: str) -> tuple[list[str], list[dict]]:
    """
    Load and validate ranking data from file.

    Args:
        ranking_file: Path to the ranking JSON file
        chat_name: Name of the chat (for error messages)

    Returns:
        Tuple of (featured_discussion_ids, brief_mention_items)

    Raises:
        RuntimeError: If featured_discussion_ids is missing or empty
    """
    try:
        with open(ranking_file, encoding="utf-8") as f:
            ranking_data = json.load(f)

        featured_discussion_ids = ranking_data.get(RankingResultKeys.FEATURED_DISCUSSION_IDS)
        if featured_discussion_ids is None:
            raise RuntimeError(f"Ranking file {ranking_file} missing '{RankingResultKeys.FEATURED_DISCUSSION_IDS}' field. " "Please re-run with force_refresh_discussions_ranking=true.")
        if not featured_discussion_ids:
            raise RuntimeError(f"No featured_discussion_ids found in ranking for chat '{chat_name}'.")

        brief_mention_items = ranking_data.get(RankingResultKeys.BRIEF_MENTION_ITEMS, [])

        return featured_discussion_ids, brief_mention_items
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading ranking data: {e}, ranking_file={ranking_file}, chat_name={chat_name}")
        raise RuntimeError(f"Failed to load ranking data: {e}") from e


def load_featured_discussions(data_source_path: str, featured_discussion_ids: list[str], chat_name: str) -> list[dict]:
    """
    Load discussions and filter to only featured ones.

    Args:
        data_source_path: Path to the discussions JSON file
        featured_discussion_ids: List of IDs to include
        chat_name: Name of the chat (for error messages)

    Returns:
        List of featured discussion dictionaries

    Raises:
        RuntimeError: If no matching discussions found
    """
    try:
        with open(data_source_path, encoding="utf-8") as f:
            all_discussions_data = json.load(f)

        all_discussions = all_discussions_data.get(DiscussionKeys.DISCUSSIONS, []) if isinstance(all_discussions_data, dict) else all_discussions_data

        featured_ids_set = set(featured_discussion_ids)
        featured_discussions = [d for d in all_discussions if d.get(DiscussionKeys.ID) in featured_ids_set]

        if not featured_discussions:
            raise RuntimeError(f"No matching discussions found for featured IDs in chat '{chat_name}'. " f"Featured IDs: {featured_discussion_ids}")

        return featured_discussions
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading featured discussions: {e}, data_source_path={data_source_path}, chat_name={chat_name}")
        raise RuntimeError(f"Failed to load featured discussions: {e}") from e


def simplify_discussions_for_prompt(discussions: list[dict]) -> list[dict]:
    """
    Simplify discussions to id, title, and nutshell/summary only.

    Controls token usage when discussions are passed as context for the
    worth_mentioning section prompt.

    Args:
        discussions: Full discussion dictionaries

    Returns:
        List of simplified discussion dictionaries
    """
    simplified = []
    for d in discussions:
        entry = {
            DiscussionKeys.ID: d.get(DiscussionKeys.ID),
            DiscussionKeys.TITLE: d.get(DiscussionKeys.TITLE, ""),
        }
        if d.get(DiscussionKeys.NUTSHELL):
            entry[DiscussionKeys.NUTSHELL] = d[DiscussionKeys.NUTSHELL]
        elif d.get("summary"):
            entry["summary"] = d["summary"]
        elif d.get(DiscussionKeys.MESSAGES):
            entry["first_messages"] = [m.get("text", "") for m in d[DiscussionKeys.MESSAGES][:5] if m.get("text")]
        simplified.append(entry)
    return simplified


def load_non_featured_discussions(
    data_source_path: str,
    featured_discussion_ids: list[str],
) -> list[dict]:
    """
    Load discussions that are NOT in the featured list.

    Returns simplified versions (id, title, nutshell/summary only) to control token usage
    when passed as fallback context for the worth_mentioning section.

    Args:
        data_source_path: Path to the discussions JSON file
        featured_discussion_ids: List of featured IDs to exclude

    Returns:
        List of simplified non-featured discussion dictionaries
    """
    try:
        with open(data_source_path, encoding="utf-8") as f:
            all_discussions_data = json.load(f)

        all_discussions = all_discussions_data.get(DiscussionKeys.DISCUSSIONS, []) if isinstance(all_discussions_data, dict) else all_discussions_data

        featured_ids_set = set(featured_discussion_ids)
        non_featured = [d for d in all_discussions if d.get(DiscussionKeys.ID) not in featured_ids_set]

        simplified = simplify_discussions_for_prompt(non_featured)
        logger.info(f"Loaded {len(simplified)} non-featured discussions as fallback context for worth_mentioning")
        return simplified
    except Exception as e:
        logger.warning(f"Failed to load non-featured discussions: {e}")
        return []


# =============================================================================
# MONGODB INITIALIZATION HELPERS
# =============================================================================


def generate_newsletter_id(run_id: str, chat_name: str) -> str:
    """
    Generate newsletter ID from run_id and chat_name.

    Args:
        run_id: MongoDB run ID
        chat_name: Chat name to slugify

    Returns:
        Newsletter ID in format: {run_id}_nl_{chat_slug}

    Raises:
        ValueError: If run_id or chat_name is invalid
    """
    try:
        if not run_id or not isinstance(run_id, str):
            raise ValueError(f"Invalid run_id: {run_id}")
        if not chat_name or not isinstance(chat_name, str):
            raise ValueError(f"Invalid chat_name: {chat_name}")

        chat_slug = re.sub(r"[^a-z0-9]+", "_", chat_name.lower()).strip("_")
        return f"{run_id}_nl_{chat_slug}"
    except Exception as e:
        logger.error(f"Failed to generate newsletter ID: run_id={run_id}, chat_name={chat_name}, error={e}")
        raise


async def initialize_mongodb_repository(mongodb_run_id: str | None, chat_name: str) -> tuple[Any | None, str | None]:
    """
    Initialize MongoDB repository for newsletter persistence.

    Args:
        mongodb_run_id: MongoDB run ID (None to skip)
        chat_name: Chat name for newsletter ID generation

    Returns:
        Tuple of (newsletters_repo, newsletter_id) - both None if disabled
    """
    if not mongodb_run_id:
        return None, None

    try:
        from db.connection import get_database
        from db.repositories.newsletters import NewslettersRepository

        db = await get_database()
        newsletters_repo = NewslettersRepository(db)

        newsletter_id = generate_newsletter_id(mongodb_run_id, chat_name)
        logger.info(f"MongoDB persistence enabled for newsletter: {newsletter_id}")

        return newsletters_repo, newsletter_id

    except Exception as e:
        logger.warning(f"Failed to initialize MongoDB repository: {e}")
        return None, None


# =============================================================================
# OUTPUT VALIDATION HELPERS
# =============================================================================


def validate_content_generation_output(content_result: dict | None, result_newsletter_id: str | None, newsletter_json_path: str | None, newsletter_md_path: str | None, state: dict[str, Any]) -> tuple[str, str]:
    """
    Validate content generation output and determine file paths.

    Handles both MongoDB-first and legacy file-based modes.

    Args:
        content_result: Result from content generator
        result_newsletter_id: Newsletter ID from MongoDB (if saved)
        newsletter_json_path: JSON file path from result
        newsletter_md_path: Markdown file path from result
        state: Graph state for expected paths fallback

    Returns:
        Tuple of (newsletter_json_path, newsletter_md_path)

    Raises:
        RuntimeError: If content generation failed or files missing
    """
    try:
        if not content_result:
            raise RuntimeError("Content generation returned no result")

        # MongoDB-first validation
        if result_newsletter_id:
            logger.info(f"Newsletter saved to MongoDB: {result_newsletter_id}")
            settings = get_settings()
            if not settings.database.enable_file_outputs:
                # No file paths expected - use expected paths for state compatibility
                newsletter_json_path = state.get(Keys.EXPECTED_NEWSLETTER_JSON)
                newsletter_md_path = state.get(Keys.EXPECTED_NEWSLETTER_MD)
                logger.debug("File outputs disabled - using expected paths for state compatibility")
        else:
            # Legacy file-based mode - validate files exist
            if not newsletter_json_path or not os.path.exists(newsletter_json_path):
                raise RuntimeError("Content generation did not create expected JSON file")
            if not newsletter_md_path or not os.path.exists(newsletter_md_path):
                raise RuntimeError("Content generation did not create expected markdown file")

        return newsletter_json_path, newsletter_md_path
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating content generation output: {e}, newsletter_id={result_newsletter_id}")
        raise RuntimeError(f"Failed to validate content generation output: {e}") from e


# =============================================================================
# NEWSLETTER LOADING HELPERS
# =============================================================================


async def load_newsletter_for_evaluation(result_newsletter_id: str | None, newsletters_repo: Any | None, newsletter_json_path: str | None) -> dict:
    """
    Load newsletter content for evaluation scoring.

    Tries MongoDB first, falls back to file.

    Args:
        result_newsletter_id: Newsletter ID in MongoDB
        newsletters_repo: MongoDB repository instance
        newsletter_json_path: Path to JSON file (fallback)

    Returns:
        Newsletter content dict (empty if loading fails)
    """
    newsletter_result = {}

    try:
        if result_newsletter_id and newsletters_repo:
            # MongoDB-first: retrieve from database (native async)
            content = await newsletters_repo.get_newsletter_content(result_newsletter_id, version="original", format="json")
            if content:
                newsletter_result = content
                logger.debug(f"Loaded newsletter from MongoDB: {result_newsletter_id}")
        elif newsletter_json_path and os.path.exists(newsletter_json_path):
            # Legacy: load from file
            with open(newsletter_json_path) as f:
                newsletter_result = json.load(f)
            logger.debug(f"Loaded newsletter from file: {newsletter_json_path}")
    except Exception as e:
        logger.warning(f"Failed to load newsletter for evaluation: {e}")

    return newsletter_result


# =============================================================================
# EVALUATION SCORING HELPERS
# =============================================================================


def score_newsletter_if_available(span: Any | None, newsletter_result: dict, trace_id: str | None) -> None:
    """
    Score newsletter structure if span and content are available.

    This is a fail-soft operation - errors are logged but not raised.

    Args:
        span: Langfuse span for observation ID
        newsletter_result: Newsletter content dict
        trace_id: Langfuse trace ID
    """
    try:
        if not span or not newsletter_result:
            return

        score_result = score_newsletter_structure(trace_id=trace_id, observation_id=span.id, result=newsletter_result)
        logger.info(f"Newsletter structural score: {score_result.score:.2f}")
    except Exception as e:
        logger.warning(f"Failed to score newsletter structure: {e}, trace_id={trace_id}")


def log_mongodb_persistence_success(result_newsletter_id: str | None) -> None:
    """
    Log successful MongoDB persistence.

    Args:
        result_newsletter_id: Newsletter ID that was persisted
    """
    try:
        if result_newsletter_id:
            logger.info(f"Newsletter persisted to MongoDB: {result_newsletter_id} " f"(content stored, not just file paths)")
    except Exception as e:
        logger.warning(f"Failed to log MongoDB persistence success: {e}, newsletter_id={result_newsletter_id}")
