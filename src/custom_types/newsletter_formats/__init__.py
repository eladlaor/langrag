"""
Newsletter Format Registry

Auto-discovers format plugins from subdirectories.
Each format directory must contain:
- __init__.py with FORMAT_CLASS attribute pointing to the format class

Usage:
    from custom_types.newsletter_formats import get_format, list_formats

    # Get a specific format
    langtalks = get_format("langtalks_format")

    # List all available formats
    formats = list_formats()  # ["langtalks_format", "mcp_israel_format"]

    # Get all formats as dict
    all_formats = get_all_formats()
"""

import importlib
import logging
from pathlib import Path

from .base import NewsletterFormatBase, NewsletterFormatProtocol

logger = logging.getLogger(__name__)

_FORMAT_REGISTRY: dict[str, NewsletterFormatBase] = {}
_INITIALIZED = False


def _discover_formats() -> None:
    """
    Scan subdirectories and register formats.

    Each subdirectory is expected to be a format plugin with:
    - __init__.py containing FORMAT_CLASS = <FormatClass>
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    formats_dir = Path(__file__).parent

    for subdir in formats_dir.iterdir():
        # Skip non-directories, private dirs, and __pycache__
        if not subdir.is_dir():
            continue
        if subdir.name.startswith("_"):
            continue
        if subdir.name == "__pycache__":
            continue

        try:
            module = importlib.import_module(f".{subdir.name}", package=__name__)
            if hasattr(module, "FORMAT_CLASS"):
                format_class = module.FORMAT_CLASS
                format_instance = format_class()
                _FORMAT_REGISTRY[format_instance.format_name] = format_instance
                logger.debug(f"Registered newsletter format: {format_instance.format_name} " f"({format_instance.format_display_name})")
            else:
                logger.debug(f"Skipping {subdir.name}: no FORMAT_CLASS attribute found")
        except Exception as e:
            logger.warning(f"Failed to load format from {subdir.name}: {e}")

    _INITIALIZED = True
    logger.info(f"Discovered {len(_FORMAT_REGISTRY)} newsletter formats: {list(_FORMAT_REGISTRY.keys())}")


def get_format(format_name: str) -> NewsletterFormatBase:
    """
    Get a format by name.

    Args:
        format_name: The format identifier (e.g., "langtalks_format")

    Returns:
        NewsletterFormatBase instance

    Raises:
        KeyError: If format not found
    """
    _discover_formats()
    if format_name not in _FORMAT_REGISTRY:
        available = list(_FORMAT_REGISTRY.keys())
        raise KeyError(f"Format '{format_name}' not found. Available formats: {available}")
    return _FORMAT_REGISTRY[format_name]


def list_formats() -> list[str]:
    """
    Return list of available format names.

    Returns:
        List of format name strings
    """
    _discover_formats()
    return list(_FORMAT_REGISTRY.keys())


def get_all_formats() -> dict[str, NewsletterFormatBase]:
    """
    Return all registered formats.

    Returns:
        Dictionary mapping format names to format instances
    """
    _discover_formats()
    return _FORMAT_REGISTRY.copy()


def is_valid_format(format_name: str) -> bool:
    """
    Check if a format name is valid.

    Args:
        format_name: The format identifier to check

    Returns:
        True if format exists, False otherwise
    """
    _discover_formats()
    return format_name in _FORMAT_REGISTRY


def format_supports_hitl(format_name: str) -> bool:
    """
    Check if a format supports Human-in-the-Loop selection.

    Args:
        format_name: The format identifier

    Returns:
        True if format supports HITL, False otherwise

    Raises:
        KeyError: If format not found
    """
    fmt = get_format(format_name)
    return getattr(fmt, "supports_hitl", True)


def format_handles_links_internally(format_name: str) -> bool:
    """
    Check if a format handles links during content generation.

    When True, the link enrichment stage should be skipped as links
    are already embedded in the generated content.

    Args:
        format_name: The format identifier

    Returns:
        True if format handles links internally, False otherwise

    Raises:
        KeyError: If format not found
    """
    fmt = get_format(format_name)
    return getattr(fmt, "handles_links_internally", False)


def get_format_capabilities(format_name: str) -> dict:
    """
    Get all capabilities for a format as a dictionary.

    Args:
        format_name: The format identifier

    Returns:
        Dictionary with format capabilities:
        {
            "format_name": str,
            "display_name": str,
            "language": str,
            "supports_hitl": bool,
            "handles_links_internally": bool
        }

    Raises:
        KeyError: If format not found
    """
    fmt = get_format(format_name)
    return {
        "format_name": fmt.format_name,
        "display_name": fmt.format_display_name,
        "language": fmt.language,
        "supports_hitl": getattr(fmt, "supports_hitl", True),
        "handles_links_internally": getattr(fmt, "handles_links_internally", False),
    }


# Export base classes and functions
__all__ = [
    "NewsletterFormatBase",
    "NewsletterFormatProtocol",
    "get_format",
    "list_formats",
    "get_all_formats",
    "is_valid_format",
    "format_supports_hitl",
    "format_handles_links_internally",
    "get_format_capabilities",
]
