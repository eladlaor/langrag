"""
Centralized validation helpers for fail-fast input checking.

All helpers raise descriptive exceptions on invalid input.
"""

import os
import re
from typing import Any

from custom_types.exceptions import PathContainmentError


def resolve_path_within_base(base: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> str:
    """Resolve ``candidate`` against ``base`` and enforce real path containment.

    Defends client-supplied path inputs (file-serving, run deletion) against
    traversal. Both base and the resolved target are passed through
    ``os.path.realpath`` (resolving symlinks and ``..`` segments), then the target
    is required to live inside the base via ``os.path.commonpath`` — NOT a string
    ``startswith`` prefix check, which is bypassable (e.g. ``/output-evil``).

    A ``candidate`` that is already absolute and inside the base is accepted as-is;
    a relative ``candidate`` is joined onto the base before resolution.

    Args:
        base: Allowed root directory (may be relative, e.g. "output"; it is realpath'd).
        candidate: Client-supplied path, relative to ``base`` or already nested under it.

    Returns:
        The resolved absolute path as a string, guaranteed to be inside ``base``.

    Raises:
        PathContainmentError: If the resolved target escapes ``base``.
    """
    base_real = os.path.realpath(os.fspath(base))
    candidate_str = os.fspath(candidate)
    joined = candidate_str if os.path.isabs(candidate_str) else os.path.join(base_real, candidate_str)
    target_real = os.path.realpath(joined)

    try:
        common = os.path.commonpath([base_real, target_real])
    except ValueError as e:
        # Different drives / mixed absolute-relative — treat as escape.
        raise PathContainmentError(f"Path '{candidate_str}' cannot be contained within base '{base_real}': {e}") from e

    if common != base_real:
        raise PathContainmentError(f"Path '{candidate_str}' resolves to '{target_real}', which escapes base '{base_real}'")

    return target_real


def require_fields(data: dict[str, Any], fields: list[str], context: str = "") -> None:
    """Validate required fields exist and are non-empty. Raises ValueError on failure."""
    missing = [f for f in fields if not data.get(f)]
    if missing:
        ctx = f" in {context}" if context else ""
        raise ValueError(f"Missing required fields{ctx}: {', '.join(missing)}")


def validate_date_range(start_date: str | None, end_date: str | None) -> None:
    """Validate date range is valid. Raises ValueError if start > end."""
    if start_date and end_date and start_date > end_date:
        raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date})")


def validate_single_chat_state(state: dict, required: list[str] | None = None) -> None:
    """Validate SingleChatState fields. Raises on invalid."""
    default_required = ["chat_name", "run_id"]
    require_fields(state, required or default_required, context="SingleChatState")
    validate_date_range(state.get("start_date"), state.get("end_date"))


def validate_orchestrator_state(state: dict, required: list[str] | None = None) -> None:
    """Validate ParallelOrchestratorState fields. Raises on invalid."""
    default_required = ["run_id", "data_source_name"]
    require_fields(state, required or default_required, context="ParallelOrchestratorState")


# Maximum allowed chat name length
_MAX_CHAT_NAME_LENGTH = 200

# Allowed characters: alphanumeric, spaces, hyphens, underscores, hash, Hebrew chars, common punctuation
_CHAT_NAME_PATTERN = re.compile(r"^[\w\s\-#.,()'\u0590-\u05FF]+$", re.UNICODE)


def sanitize_chat_name_for_prompt(chat_name: str) -> str:
    """
    Sanitize chat_name before interpolation into LLM prompts.

    Prevents prompt injection by validating format and escaping dangerous content.
    Chat names come from user input (API request whatsapp_chat_names_to_include)
    and are interpolated into system prompts for discussion separation.

    Args:
        chat_name: Raw chat name from user input

    Returns:
        Sanitized chat name safe for prompt interpolation

    Raises:
        ValueError: If chat_name contains suspicious patterns
    """
    if not chat_name or not chat_name.strip():
        raise ValueError("chat_name cannot be empty")

    chat_name = chat_name.strip()

    if len(chat_name) > _MAX_CHAT_NAME_LENGTH:
        raise ValueError(f"chat_name exceeds maximum length of {_MAX_CHAT_NAME_LENGTH} characters")

    if not _CHAT_NAME_PATTERN.match(chat_name):
        raise ValueError(f"chat_name contains invalid characters: '{chat_name}'")

    return chat_name
