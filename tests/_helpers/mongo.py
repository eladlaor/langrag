"""Shared MongoDB availability skip marker for test modules.

Importable from any test file as `from tests._helpers.mongo import requires_mongodb`.
"""

from __future__ import annotations

import pytest


def _mongodb_available() -> bool:
    """Probe MongoDB synchronously.

    Uses pymongo's sync client (not motor) so the probe runs without any
    event-loop entanglement — Motor's loop ownership rules make a one-shot
    async ping from outside an asyncio context fragile in Python 3.13.
    """
    try:
        from pymongo import MongoClient

        from config import get_settings

        url = get_settings().get_mongodb_url()
        # `mongodb-atlas-local` runs as a single-node replica set and
        # advertises its internal hostname during discovery. From the host
        # we connect via the published port, so we must bypass replica-set
        # discovery to avoid following the internal hostname.
        client = MongoClient(url, serverSelectionTimeoutMS=2000, directConnection=True)
        try:
            client.admin.command("ping")
            return True
        finally:
            client.close()
    except Exception:
        return False


requires_mongodb = pytest.mark.skipif(
    not _mongodb_available(),
    reason="MongoDB not available (start the docker compose `mongodb` service)",
)
