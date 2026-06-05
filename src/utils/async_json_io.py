"""Async JSON file I/O helpers.

Reading/writing JSON inside ``async def`` graph nodes with bare ``open()`` +
``json.load``/``json.dump`` blocks the event loop for the duration of the I/O.
Under the parallel orchestrator (many chat workers sharing one loop), a single
blocking read stalls every other concurrent worker. These helpers offload the
blocking work to a thread so the loop stays responsive.

Use ``load_json_async`` / ``dump_json_async`` from any async context that touches
JSON files. The synchronous ``_load_json``/``_dump_json`` are the thread targets
and should not be called directly from the event loop.
"""

import asyncio
import json
from typing import Any


def _load_json(file_path: str, encoding: str = "utf-8") -> Any:
    """Load and parse a JSON file (sync; the thread target for load_json_async)."""
    with open(file_path, encoding=encoding) as f:
        return json.load(f)


def _dump_json(file_path: str, data: Any, *, ensure_ascii: bool = False, indent: int = 2, encoding: str = "utf-8") -> None:
    """Serialize data as JSON to a file (sync; the thread target for dump_json_async)."""
    with open(file_path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)


async def load_json_async(file_path: str, encoding: str = "utf-8") -> Any:
    """Load and parse a JSON file off the event loop.

    Args:
        file_path: Path to the JSON file.
        encoding: Text encoding (default utf-8).

    Returns:
        The parsed JSON content.
    """
    return await asyncio.to_thread(_load_json, file_path, encoding)


async def dump_json_async(file_path: str, data: Any, *, ensure_ascii: bool = False, indent: int = 2, encoding: str = "utf-8") -> None:
    """Serialize and write data as JSON to a file off the event loop.

    Args:
        file_path: Destination path.
        data: JSON-serializable object.
        ensure_ascii: Passed through to json.dump (default False to preserve Hebrew/Unicode).
        indent: Pretty-print indent (default 2).
        encoding: Text encoding (default utf-8).
    """
    await asyncio.to_thread(_dump_json, file_path, data, ensure_ascii=ensure_ascii, indent=indent, encoding=encoding)
