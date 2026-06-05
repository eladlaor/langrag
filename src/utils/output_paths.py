"""Output path construction and resolution for periodic-newsletter runs.

Single source of truth for the on-disk layout of periodic-newsletter output. Runs are
nested per community:

    <base_output_dir>/<data_source_name>/<data_source_name>_<start>_to_<end>/

The leaf directory name (the ``run_id``) keeps its full ``{data_source}_{start}_to_{end}``
form, so callers that key a run by its leaf basename are unaffected. Only the community
parent level is inserted, and resolution derives the community by parsing the run_id.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# Pattern: {data_source}_{start_date}_to_{end_date}
# data_source may contain underscores (e.g. "mcp_israel", "n8n_israel"), so the leading
# group is greedy up to the trailing "_<date>_to_<date>" anchor. The community group
# forbids path separators ([^/\\]+) so a crafted run_id can never yield a traversal
# segment (e.g. "../../etc"); resolve_run_dir is then safe in isolation and does not
# rely solely on every caller wrapping it in resolve_path_within_base.
RUN_DIR_PATTERN = re.compile(r"^([^/\\]+)_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$")

# Community extraction tolerates a trailing suffix after the end date (e.g. "_merged"),
# which some legacy run dirs carry. The community is always the segment before the
# "_<start>_to_<end>" anchor, and likewise may not contain path separators.
RUN_DIR_COMMUNITY_PATTERN = re.compile(r"^([^/\\]+)_\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2}(?:_.+)?$")


def parse_run_id(run_id: str) -> tuple[str, str, str] | None:
    """Parse a run_id into (data_source, start_date, end_date), or None if malformed.

    Strict: a trailing suffix after the end date is not accepted. Use
    ``community_of_run_id`` when only the community is needed and suffixes may be present.

    Args:
        run_id: Leaf run directory name, e.g. "langtalks_2025-10-01_to_2025-10-26".
    """
    try:
        match = RUN_DIR_PATTERN.match(run_id)
        if match:
            return (match.group(1), match.group(2), match.group(3))
        return None
    except Exception as e:
        logger.debug(f"Failed to parse run_id '{run_id}': {e}")
        return None


def community_of_run_id(run_id: str) -> str | None:
    """Extract just the community (data_source) from a run_id, or None if not a run dir.

    Tolerates a trailing suffix after the end date (e.g. legacy "..._merged" dirs).
    """
    try:
        match = RUN_DIR_COMMUNITY_PATTERN.match(run_id)
        return match.group(1) if match else None
    except Exception as e:
        logger.debug(f"Failed to extract community from run_id '{run_id}': {e}")
        return None


def build_run_output_dir(base_output_dir: str, data_source_name: str, start_date: str, end_date: str) -> str:
    """Build the nested run output directory path for a periodic-newsletter run.

    Args:
        base_output_dir: e.g. "output/generate_periodic_newsletter".
        data_source_name: Community identifier, e.g. "langtalks".
        start_date: Run start date (YYYY-MM-DD).
        end_date: Run end date (YYYY-MM-DD).

    Returns:
        "<base_output_dir>/<data_source_name>/<data_source_name>_<start>_to_<end>".
    """
    run_id = f"{data_source_name}_{start_date}_to_{end_date}"
    return os.path.join(base_output_dir, data_source_name, run_id)


def resolve_run_dir(periodic_base: str, run_id: str) -> str:
    """Resolve a run_id to its nested directory under the periodic base.

    Derives the community from the run_id and returns
    "<periodic_base>/<community>/<run_id>".

    Args:
        periodic_base: e.g. "output/generate_periodic_newsletter".
        run_id: Leaf run directory name, e.g. "langtalks_2025-10-01_to_2025-10-26".

    Raises:
        ValueError: If run_id does not match the expected pattern.
    """
    community = community_of_run_id(run_id)
    if not community:
        raise ValueError(f"Cannot resolve run directory: malformed run_id '{run_id}'")
    return os.path.join(periodic_base, community, run_id)
