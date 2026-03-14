"""
Observability utilities with fail-safe logging.

These functions never raise - they log errors and continue.
"""

import logging
from observability.llm.langfuse_client import flush_langfuse

logger = logging.getLogger(__name__)


def safe_flush_langfuse(context: str = "") -> bool:
    """
    Flush Langfuse traces with error logging.

    Returns True if successful, False if failed.
    Never raises - logs error and continues (fail-safe for observability).
    """
    try:
        flush_langfuse()
        logger.debug(f"Langfuse flush successful{f' ({context})' if context else ''}")
        return True
    except Exception as e:
        logger.warning(f"Langfuse flush failed{f' ({context})' if context else ''}: {e}", exc_info=True, extra={"langfuse_error": str(e), "context": context})
        return False
