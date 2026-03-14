"""
Newsletter History Loader

Loads and parses previous newsletters to extract topic information
for repetition detection in new newsletter generation.

Supports both MongoDB (default) and file-based (legacy) loading.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import get_settings
from constants import (
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_AFTER_SELECTION,
    DIR_NAME_LINK_ENRICHMENT,
    DIR_NAME_NEWSLETTER,
    DIR_NAME_PER_CHAT,
    OUTPUT_FILENAME_ENRICHED_JSON,
    OUTPUT_FILENAME_ENRICHED_SUMMARY_JSON,
    OUTPUT_FILENAME_NEWSLETTER_JSON,
)
from custom_types.field_keys import NewsletterStructureKeys, DbFieldKeys
from constants import NewsletterVersionType

logger = logging.getLogger(__name__)


@dataclass
class PreviousNewsletterContext:
    """Context from a single previous newsletter edition."""

    edition_date: str  # e.g., "2025-10-01_to_2025-10-14"
    data_source: str  # e.g., "langtalks"
    primary_topics: list[str] = field(default_factory=list)  # Discussion titles
    primary_nutshells: list[str] = field(default_factory=list)  # Brief summary per primary topic
    secondary_topics: list[str] = field(default_factory=list)  # Discussion titles
    secondary_nutshells: list[str] = field(default_factory=list)  # Brief summary per secondary topic
    worth_mentioning: list[str] = field(default_factory=list)  # One-liners
    newsletter_path: str = ""  # Path to the newsletter JSON for reference


@dataclass
class PreviousNewslettersContext:
    """Aggregated context from multiple previous newsletters."""

    newsletters: list[PreviousNewsletterContext] = field(default_factory=list)
    total_editions: int = 0
    date_range_covered: str = ""  # e.g., "2025-09-01 to 2025-10-26"


def _parse_run_directory_name(dir_name: str) -> tuple[str, str, str] | None:
    """
    Parse a run directory name to extract data source and dates.

    Args:
        dir_name: Directory name like "langtalks_2025-10-01_to_2025-10-26"

    Returns:
        Tuple of (data_source, start_date, end_date) or None if parsing fails
    """
    try:
        # Pattern: {data_source}_{start_date}_to_{end_date}
        # data_source can contain underscores (e.g., "mcp_israel", "n8n_israel")
        pattern = r"^(.+)_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$"
        match = re.match(pattern, dir_name)
        if match:
            data_source = match.group(1)
            start_date = match.group(2)
            end_date = match.group(3)
            return (data_source, start_date, end_date)
        return None
    except Exception as e:
        logger.debug(f"Failed to parse directory name '{dir_name}': {e}")
        return None


def _find_newsletter_json(run_dir: Path) -> Path | None:
    """
    Find the newsletter JSON file in a run directory.

    Checks locations in priority order:
    1. consolidated/after_selection/link_enrichment/enriched_newsletter.json
    2. consolidated/link_enrichment/enriched_newsletter_summary.json
    3. consolidated/newsletter/newsletter_summary.json
    4. per_chat/{first_chat}/newsletter/newsletter_summary.json

    Args:
        run_dir: Path to the run directory

    Returns:
        Path to newsletter JSON or None if not found
    """
    # Priority 1: After selection (HITL flow)
    path = run_dir / DIR_NAME_CONSOLIDATED / DIR_NAME_AFTER_SELECTION / DIR_NAME_LINK_ENRICHMENT / OUTPUT_FILENAME_ENRICHED_JSON
    if path.exists():
        return path

    # Priority 2: Consolidated link enrichment
    path = run_dir / DIR_NAME_CONSOLIDATED / DIR_NAME_LINK_ENRICHMENT / OUTPUT_FILENAME_ENRICHED_SUMMARY_JSON
    if path.exists():
        return path

    # Priority 3: Consolidated newsletter
    path = run_dir / DIR_NAME_CONSOLIDATED / DIR_NAME_NEWSLETTER / OUTPUT_FILENAME_NEWSLETTER_JSON
    if path.exists():
        return path

    # Priority 4: First per-chat newsletter
    per_chat_dir = run_dir / DIR_NAME_PER_CHAT
    if per_chat_dir.exists():
        for chat_dir in sorted(per_chat_dir.iterdir()):
            if chat_dir.is_dir():
                path = chat_dir / DIR_NAME_NEWSLETTER / OUTPUT_FILENAME_NEWSLETTER_JSON
                if path.exists():
                    return path

    return None


def _extract_topics_from_newsletter(newsletter_path: Path) -> PreviousNewsletterContext | None:
    """
    Extract topic information from a newsletter JSON file.

    Args:
        newsletter_path: Path to the newsletter JSON file

    Returns:
        PreviousNewsletterContext or None if extraction fails
    """
    try:
        with open(newsletter_path, encoding="utf-8") as f:
            data = json.load(f)

        # Extract primary discussion title and nutshell
        primary_topics = []
        primary_nutshells = []
        primary_discussion = data.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {})
        if primary_discussion:
            title = primary_discussion.get(NewsletterStructureKeys.TITLE, "")
            if title:
                primary_topics.append(title)
                # Extract first bullet point as nutshell
                bullets = primary_discussion.get(NewsletterStructureKeys.BULLET_POINTS, [])
                if bullets and isinstance(bullets[0], dict):
                    nutshell = f"{bullets[0].get(NewsletterStructureKeys.LABEL, '')}: {bullets[0].get(NewsletterStructureKeys.CONTENT, '')}"
                    primary_nutshells.append(nutshell[:200])
                else:
                    primary_nutshells.append("")

        # Extract secondary discussion titles and nutshells
        secondary_topics = []
        secondary_nutshells = []
        for disc in data.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, []):
            title = disc.get(NewsletterStructureKeys.TITLE, "")
            if title:
                secondary_topics.append(title)
                bullets = disc.get(NewsletterStructureKeys.BULLET_POINTS, [])
                if bullets and isinstance(bullets[0], dict):
                    nutshell = f"{bullets[0].get(NewsletterStructureKeys.LABEL, '')}: {bullets[0].get(NewsletterStructureKeys.CONTENT, '')}"
                    secondary_nutshells.append(nutshell[:200])
                else:
                    secondary_nutshells.append("")

        # Extract worth mentioning items
        worth_mentioning = data.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
        # Ensure it's a list of strings
        if isinstance(worth_mentioning, list):
            worth_mentioning = [str(item) for item in worth_mentioning if item]
        else:
            worth_mentioning = []

        # Parse edition date from directory name
        run_dir = newsletter_path.parent.parent.parent
        if DIR_NAME_PER_CHAT in str(newsletter_path):
            run_dir = newsletter_path.parent.parent.parent.parent
        if DIR_NAME_AFTER_SELECTION in str(newsletter_path):
            run_dir = newsletter_path.parent.parent.parent.parent

        parsed = _parse_run_directory_name(run_dir.name)
        edition_date = f"{parsed[1]}_to_{parsed[2]}" if parsed else run_dir.name
        data_source = parsed[0] if parsed else "unknown"

        return PreviousNewsletterContext(
            edition_date=edition_date,
            data_source=data_source,
            primary_topics=primary_topics,
            primary_nutshells=primary_nutshells,
            secondary_topics=secondary_topics,
            secondary_nutshells=secondary_nutshells,
            worth_mentioning=worth_mentioning,
            newsletter_path=str(newsletter_path),
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse newsletter JSON at {newsletter_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to extract topics from {newsletter_path}: {e}")
        return None


async def load_previous_newsletters(
    data_source_name: str,
    current_start_date: str,
    max_newsletters: int = 5,
    output_base_dir: str = "output/generate_periodic_newsletter",
) -> PreviousNewslettersContext:
    """
    Load recent newsletters for a data source, excluding current date range.

    Uses MongoDB by default (MongoDB-first architecture).
    Falls back to file-based loading if USE_FILE_BASED_HISTORY flag is enabled.

    Args:
        data_source_name: e.g., "langtalks", "mcp_israel"
        current_start_date: Start date of current newsletter (YYYY-MM-DD)
        max_newsletters: Maximum previous newsletters to load (default: 5)
        output_base_dir: Base output directory (used only for file-based fallback)

    Returns:
        PreviousNewslettersContext with extracted topics

    Note:
        Returns empty context if no previous newsletters found (graceful degradation).
        This allows the system to function normally on first runs.
    """
    try:
        settings = get_settings()

        # Check feature flag: default to MongoDB, fallback to files if flag enabled
        if not settings.database.use_file_based_history:
            logger.info("Using MongoDB-based newsletter history loader")
            # Directly await async MongoDB loader (we're in async context)
            return await load_previous_newsletters_from_mongodb(data_source_name=data_source_name, current_start_date=current_start_date, max_newsletters=max_newsletters)

        # Fallback to file-based loader (legacy mode for rollback)
        logger.info("Using file-based newsletter history loader (legacy mode)")
        return _load_previous_newsletters_from_files(data_source_name=data_source_name, current_start_date=current_start_date, max_newsletters=max_newsletters, output_base_dir=output_base_dir)

    except Exception as e:
        logger.error(f"Error in load_previous_newsletters: {e}")
        # Graceful degradation
        return PreviousNewslettersContext()


def _load_previous_newsletters_from_files(
    data_source_name: str,
    current_start_date: str,
    max_newsletters: int = 5,
    output_base_dir: str = "output/generate_periodic_newsletter",
) -> PreviousNewslettersContext:
    """
    LEGACY: Load newsletters from filesystem (rollback support only).

    This is the original file-based implementation, kept for backward compatibility
    when USE_FILE_BASED_HISTORY=true. New code should use MongoDB loader.

    Process:
    1. List all run directories for the data source
    2. Parse directory names to extract dates
    3. Filter to runs BEFORE current_start_date
    4. Sort by end_date descending (most recent first)
    5. Load up to max_newsletters
    6. Extract topic information from each

    Args:
        data_source_name: e.g., "langtalks", "mcp_israel"
        current_start_date: Start date of current newsletter (YYYY-MM-DD)
        max_newsletters: Maximum previous newsletters to load (default: 5)
        output_base_dir: Base output directory

    Returns:
        PreviousNewslettersContext with extracted topics

    Note:
        Returns empty context if no previous newsletters found (graceful degradation).
    """
    try:
        logger.info(f"Loading previous newsletters for data_source={data_source_name}, " f"current_start_date={current_start_date}, max={max_newsletters}")

        if max_newsletters <= 0:
            logger.info("Anti-repetition disabled (max_newsletters=0)")
            return PreviousNewslettersContext()

        # Resolve output directory
        base_dir = Path(output_base_dir)
        if not base_dir.is_absolute():
            # Try relative to current working directory
            base_dir = Path.cwd() / output_base_dir

        if not base_dir.exists():
            logger.warning(f"Output directory not found: {base_dir}")
            return PreviousNewslettersContext()

        # Parse current start date for comparison
        try:
            current_date = datetime.strptime(current_start_date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid current_start_date format: {current_start_date}")
            return PreviousNewslettersContext()

        # Find matching run directories
        matching_runs = []
        for item in base_dir.iterdir():
            if not item.is_dir():
                continue

            parsed = _parse_run_directory_name(item.name)
            if not parsed:
                continue

            dir_data_source, start_date, end_date = parsed

            # Check if data source matches
            if dir_data_source != data_source_name:
                continue

            # Parse end date for comparison and sorting
            try:
                run_end_date = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                continue

            # Only include runs that ended BEFORE current start date
            if run_end_date >= current_date:
                continue

            matching_runs.append((item, run_end_date, start_date, end_date))

        # Sort by end_date descending (most recent first)
        matching_runs.sort(key=lambda x: x[1], reverse=True)

        # Load up to max_newsletters
        newsletters = []
        for run_dir, _, start_date, end_date in matching_runs[:max_newsletters]:
            newsletter_path = _find_newsletter_json(run_dir)
            if not newsletter_path:
                logger.debug(f"No newsletter JSON found in {run_dir}")
                continue

            context = _extract_topics_from_newsletter(newsletter_path)
            if context:
                newsletters.append(context)
                logger.debug(f"Loaded newsletter from {run_dir.name}: " f"{len(context.primary_topics)} primary, " f"{len(context.secondary_topics)} secondary, " f"{len(context.worth_mentioning)} worth_mentioning")

        # Build date range string
        date_range = ""
        if newsletters:
            oldest_date = newsletters[-1].edition_date.split("_to_")[0]
            newest_date = newsletters[0].edition_date.split("_to_")[1]
            date_range = f"{oldest_date} to {newest_date}"

        result = PreviousNewslettersContext(
            newsletters=newsletters,
            total_editions=len(newsletters),
            date_range_covered=date_range,
        )

        logger.info(f"Loaded {len(newsletters)} previous newsletters " f"(requested max: {max_newsletters}), " f"covering date range: {date_range or 'N/A'}")

        return result

    except Exception as e:
        logger.error(f"Unexpected error loading previous newsletters: {e}")
        # Graceful degradation - return empty context
        return PreviousNewslettersContext()


async def load_previous_newsletters_from_mongodb(
    data_source_name: str,
    current_start_date: str,
    max_newsletters: int = 5,
) -> PreviousNewslettersContext:
    """
    Load recent newsletters from MongoDB for anti-repetition.

    This is the MongoDB-first replacement for file-based history loading.
    Uses NewslettersRepository to query completed newsletters before current_start_date.

    Args:
        data_source_name: e.g., "langtalks", "mcp_israel"
        current_start_date: Start date of current newsletter (YYYY-MM-DD)
        max_newsletters: Maximum previous newsletters to load (default: 5)

    Returns:
        PreviousNewslettersContext with extracted topics

    Note:
        Returns empty context if no previous newsletters found (graceful degradation).
    """
    try:
        logger.info(f"Loading previous newsletters from MongoDB: data_source={data_source_name}, " f"current_start_date={current_start_date}, max={max_newsletters}")

        if max_newsletters <= 0:
            logger.info("Anti-repetition disabled (max_newsletters=0)")
            return PreviousNewslettersContext()

        # Initialize MongoDB repository
        from db.connection import get_database
        from db.repositories.newsletters import NewslettersRepository

        db = await get_database()
        repo = NewslettersRepository(db)

        # Query MongoDB for recent newsletters
        newsletter_docs = await repo.get_recent_newsletters_for_context(data_source_name=data_source_name, before_date=current_start_date, limit=max_newsletters)

        if not newsletter_docs:
            logger.info(f"No previous newsletters found in MongoDB for {data_source_name}")
            return PreviousNewslettersContext()

        # Extract topics from each newsletter
        newsletters = []
        for doc in newsletter_docs:
            try:
                # Extract JSON content from MongoDB document
                json_content = doc.get(DbFieldKeys.VERSIONS, {}).get(NewsletterVersionType.ORIGINAL, {}).get(DbFieldKeys.JSON_CONTENT)
                if not json_content:
                    logger.debug(f"No json_content found for newsletter {doc.get('newsletter_id')}")
                    continue

                # Extract primary discussion title and nutshell
                primary_topics = []
                primary_nutshells = []
                primary_discussion = json_content.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {})
                if primary_discussion:
                    title = primary_discussion.get(NewsletterStructureKeys.TITLE, "")
                    if title:
                        primary_topics.append(title)
                        bullets = primary_discussion.get(NewsletterStructureKeys.BULLET_POINTS, [])
                        if bullets and isinstance(bullets[0], dict):
                            nutshell = f"{bullets[0].get(NewsletterStructureKeys.LABEL, '')}: {bullets[0].get(NewsletterStructureKeys.CONTENT, '')}"
                            primary_nutshells.append(nutshell[:200])
                        else:
                            primary_nutshells.append("")

                # Extract secondary discussion titles and nutshells
                secondary_topics = []
                secondary_nutshells = []
                for disc in json_content.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, []):
                    title = disc.get(NewsletterStructureKeys.TITLE, "")
                    if title:
                        secondary_topics.append(title)
                        bullets = disc.get(NewsletterStructureKeys.BULLET_POINTS, [])
                        if bullets and isinstance(bullets[0], dict):
                            nutshell = f"{bullets[0].get(NewsletterStructureKeys.LABEL, '')}: {bullets[0].get(NewsletterStructureKeys.CONTENT, '')}"
                            secondary_nutshells.append(nutshell[:200])
                        else:
                            secondary_nutshells.append("")

                # Extract worth mentioning items
                worth_mentioning = json_content.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
                if isinstance(worth_mentioning, list):
                    worth_mentioning = [str(item) for item in worth_mentioning if item]
                else:
                    worth_mentioning = []

                # Build edition date string
                start_date = doc.get(DbFieldKeys.START_DATE, "")
                end_date = doc.get(DbFieldKeys.END_DATE, "")
                edition_date = f"{start_date}_to_{end_date}" if start_date and end_date else doc.get(DbFieldKeys.NEWSLETTER_ID, "")

                context = PreviousNewsletterContext(
                    edition_date=edition_date,
                    data_source=data_source_name,
                    primary_topics=primary_topics,
                    primary_nutshells=primary_nutshells,
                    secondary_topics=secondary_topics,
                    secondary_nutshells=secondary_nutshells,
                    worth_mentioning=worth_mentioning,
                    newsletter_path=f"mongodb://{doc.get('newsletter_id')}",  # Virtual path for reference
                )

                newsletters.append(context)
                logger.debug(f"Loaded newsletter {doc.get('newsletter_id')}: " f"{len(primary_topics)} primary, " f"{len(secondary_topics)} secondary, " f"{len(worth_mentioning)} worth_mentioning")

            except Exception as e:
                logger.error(f"Failed to extract topics from newsletter {doc.get('newsletter_id')}: {e}")
                continue

        # Build date range string
        date_range = ""
        if newsletters:
            oldest_date = newsletters[-1].edition_date.split("_to_")[0]
            newest_date = newsletters[0].edition_date.split("_to_")[1] if "_to_" in newsletters[0].edition_date else newsletters[0].edition_date
            date_range = f"{oldest_date} to {newest_date}"

        result = PreviousNewslettersContext(
            newsletters=newsletters,
            total_editions=len(newsletters),
            date_range_covered=date_range,
        )

        logger.info(f"Loaded {len(newsletters)} previous newsletters from MongoDB " f"(requested max: {max_newsletters}), " f"covering date range: {date_range or 'N/A'}")

        return result

    except Exception as e:
        logger.error(f"Unexpected error loading previous newsletters from MongoDB: {e}")
        # Graceful degradation - return empty context
        return PreviousNewslettersContext()


def format_previous_context_for_prompt(
    context: PreviousNewslettersContext | None,
    max_worth_mentioning_per_edition: int = 5,
) -> str:
    """
    Format previous newsletter context for inclusion in ranking prompt.

    Args:
        context: Previous newsletters context
        max_worth_mentioning_per_edition: Max worth mentioning items to include per edition

    Returns:
        Formatted string for prompt injection
    """
    if not context or not context.newsletters:
        return ""

    lines = []
    for nl in context.newsletters:
        lines.append(f"\n--- Newsletter: {nl.edition_date} ---")

        if nl.primary_topics:
            for i, title in enumerate(nl.primary_topics):
                nutshell = nl.primary_nutshells[i] if i < len(nl.primary_nutshells) and nl.primary_nutshells[i] else ""
                if nutshell:
                    lines.append(f"PRIMARY: {title} (summary: {nutshell})")
                else:
                    lines.append(f"PRIMARY: {title}")

        if nl.secondary_topics:
            for i, title in enumerate(nl.secondary_topics):
                nutshell = nl.secondary_nutshells[i] if i < len(nl.secondary_nutshells) and nl.secondary_nutshells[i] else ""
                if nutshell:
                    lines.append(f"SECONDARY: {title} (summary: {nutshell})")
                else:
                    lines.append(f"SECONDARY: {title}")

        if nl.worth_mentioning:
            # Limit to avoid prompt bloat
            worth_items = nl.worth_mentioning[:max_worth_mentioning_per_edition]
            lines.append(f"WORTH_MENTIONING: {'; '.join(worth_items)}")

    return "\n".join(lines)
