"""
Loguru JSON Logger Configuration

This module provides a centralized JSON logging setup using loguru with:
- Structured JSON output for machine parsing
- Israel timezone timestamp (timestamp_il)
- Context binding for trace_id, run_id, node_name
- InterceptHandler to capture standard library logging
- Configurable via environment variables

Environment Variables:
    LOG_LEVEL: Minimum log level (default: "INFO")
    LOG_FORMAT: "json" or "pretty" (default: "json")
    SERVICE_NAME: Service identifier (default: "langrag")
    ENVIRONMENT: Environment name (default: "development")

Usage:
    from observability.app import setup_logging, get_logger

    # Initialize once at startup
    setup_logging()

    # Get logger
    logger = get_logger(__name__)
    logger.info("Processing started", chat_name="LangTalks")
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger as loguru_logger
from constants import LogFormat


# ============================================================================
# CONFIGURATION
# ============================================================================

# Israel timezone for timestamp_il
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Default configuration (can be overridden via environment)
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = LogFormat.JSON
DEFAULT_SERVICE_NAME = "langrag"
DEFAULT_ENVIRONMENT = "development"


def get_config() -> dict[str, Any]:
    """Get logging configuration from environment variables."""
    return {
        "log_level": os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        "log_format": os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT).lower(),
        "service_name": os.getenv("SERVICE_NAME", DEFAULT_SERVICE_NAME),
        "environment": os.getenv("ENVIRONMENT", DEFAULT_ENVIRONMENT),
    }


# ============================================================================
# JSON SERIALIZATION
# ============================================================================


def serialize_record(record: dict[str, Any]) -> str:
    """
    Serialize a loguru record to JSON with custom schema.

    Output Schema:
    {
        "timestamp_il": "25-12-13_14-30-45",
        "timestamp_utc": "2025-12-13T12:30:45.123456Z",
        "level": "INFO",
        "message": "...",
        "module": "...",
        "function": "...",
        "line": 123,
        "trace_id": "...",
        "run_id": "...",
        "node_name": "...",
        "service": "...",
        "environment": "...",
        "extra": {}
    }
    """
    config = get_config()

    # Extract timestamp and convert to Israel time
    time_obj = record["time"]
    timestamp_il = time_obj.astimezone(ISRAEL_TZ).strftime("%y-%m-%d_%H-%M-%S")
    timestamp_utc = time_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Extract extra fields (context-bound data)
    extra = dict(record.get("extra", {}))

    # Pop known context fields from extra
    trace_id = extra.pop("trace_id", None)
    run_id = extra.pop("run_id", None)
    node_name = extra.pop("node_name", None)

    # Build the log entry
    log_entry = {
        "timestamp_il": timestamp_il,
        "timestamp_utc": timestamp_utc,
        "level": record["level"].name,
        "message": record["message"],
        "module": record["name"],
        "function": record["function"],
        "line": record["line"],
        "trace_id": trace_id,
        "run_id": run_id,
        "node_name": node_name,
        "service": config["service_name"],
        "environment": config["environment"],
        "extra": extra if extra else None,
    }

    # Remove None values for cleaner output
    log_entry = {k: v for k, v in log_entry.items() if v is not None}

    return json.dumps(log_entry, ensure_ascii=False, default=str)


def json_sink(message):
    """Custom sink that outputs serialized JSON."""
    serialized = serialize_record(message.record)
    print(serialized, file=sys.stdout, flush=True)


def pretty_format(record: dict[str, Any]) -> str:
    """Pretty format for local development (non-JSON)."""
    config = get_config()
    time_obj = record["time"]
    timestamp_il = time_obj.astimezone(ISRAEL_TZ).strftime("%y-%m-%d_%H-%M-%S")

    # Build extra info string
    extra = record.get("extra", {})
    extra_parts = []
    if extra.get("trace_id"):
        extra_parts.append(f"trace={extra['trace_id'][:8]}...")
    if extra.get("run_id"):
        extra_parts.append(f"run={extra['run_id'][:20]}...")
    if extra.get("node_name"):
        extra_parts.append(f"node={extra['node_name']}")

    extra_str = f" [{', '.join(extra_parts)}]" if extra_parts else ""

    return f"<green>{timestamp_il}</green> | " f"<level>{record['level'].name:8}</level> | " f"<cyan>{record['name']}</cyan>:<cyan>{record['function']}</cyan>:<cyan>{record['line']}</cyan>" f"{extra_str} - " f"<level>{record['message']}</level>\n"


# ============================================================================
# INTERCEPT HANDLER (Capture standard logging)
# ============================================================================


class InterceptHandler(logging.Handler):
    """
    Handler that intercepts standard logging calls and redirects to loguru.

    This ensures all logs (including from third-party libraries) go through
    our JSON formatting pipeline.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding loguru level
        try:
            level = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logged message originated
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging_module = filename == logging.__file__
            is_importlib = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging_module or is_importlib):
                break
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# ============================================================================
# SETUP FUNCTIONS
# ============================================================================

_logging_initialized = False


def setup_logging(
    level: str | None = None,
    format_type: str | None = None,
) -> None:
    """
    Initialize loguru logging with JSON output.

    Call this once at application startup, before other imports if possible.

    Args:
        level: Log level override (default: from LOG_LEVEL env var)
        format_type: Format override - "json" or "pretty" (default: from LOG_FORMAT env var)

    Example:
        # In main.py, at the very top
        from observability.app import setup_logging
        setup_logging()
    """
    global _logging_initialized

    if _logging_initialized:
        return

    config = get_config()
    log_level = level or config["log_level"]
    log_format = format_type or config["log_format"]

    # Remove default loguru handler
    loguru_logger.remove()

    # Add our custom sink based on format
    if log_format == LogFormat.JSON:
        loguru_logger.add(
            json_sink,
            level=log_level,
            enqueue=True,  # Thread-safe async logging
            backtrace=True,
            diagnose=True,
        )
    else:
        # Pretty format for local development
        loguru_logger.add(
            sys.stderr,
            level=log_level,
            format=pretty_format,
            colorize=True,
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )

    # Intercept standard library logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Intercept specific loggers from common libraries
    for logger_name in [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "httpx",
        "httpcore",
        "openai",
        "langchain",
        "langgraph",
        "langfuse",
    ]:
        logging.getLogger(logger_name).handlers = [InterceptHandler()]
        logging.getLogger(logger_name).propagate = False

    _logging_initialized = True

    loguru_logger.info(
        "Logging initialized",
        format=log_format,
        level=log_level,
        service=config["service_name"],
        environment=config["environment"],
    )


def get_logger(name: str | None = None) -> loguru_logger.__class__:
    """
    Get a logger instance, optionally bound to a module name.

    Args:
        name: Module name (typically __name__)

    Returns:
        Loguru logger, optionally bound with module context

    Example:
        logger = get_logger(__name__)
        logger.info("Processing started")
    """
    if name:
        return loguru_logger.bind(module=name)
    return loguru_logger


# Expose the raw loguru logger for advanced usage
logger = loguru_logger
