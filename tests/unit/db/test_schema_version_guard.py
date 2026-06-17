"""Tests for the startup schema-version guard.

The guard refuses to start the process if any stored document is below the
minimum supported schema_version for its collection (there is no read-path
migration to upgrade it). Requires the real MongoDB fixture.
"""

from __future__ import annotations

import uuid

import pytest

from constants import (
    COLLECTION_RUNS,
    CURRENT_SCHEMA_VERSION_RUN,
    SCHEMA_VERSION_FIELD,
)
from db.indexes import ensure_schema_versions
from tests._helpers.mongo import requires_mongodb


@requires_mongodb
async def test_guard_passes_on_current_documents(db):
    """A current-version document does not trip the guard."""
    run_id = f"sv-ok-{uuid.uuid4().hex[:12]}"
    await db[COLLECTION_RUNS].insert_one(
        {"run_id": run_id, SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_RUN}
    )
    try:
        await ensure_schema_versions(db)  # must not raise
    finally:
        await db[COLLECTION_RUNS].delete_one({"run_id": run_id})


@requires_mongodb
async def test_guard_raises_on_stale_document(db):
    """A document below the minimum supported version trips the guard."""
    run_id = f"sv-stale-{uuid.uuid4().hex[:12]}"
    await db[COLLECTION_RUNS].insert_one(
        {"run_id": run_id, SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_RUN - 1}
    )
    try:
        with pytest.raises(RuntimeError, match="below the minimum supported"):
            await ensure_schema_versions(db)
    finally:
        await db[COLLECTION_RUNS].delete_one({"run_id": run_id})


@requires_mongodb
async def test_guard_ignores_missing_version_field(db):
    """A pre-versioning document (no schema_version) does NOT trip the guard.

    The stamp was added additively, so field-less legacy docs read back fine via
    model defaults. Treating them as stale would block startup on every existing
    deployment; only an explicit too-low version is a real migration signal.
    """
    run_id = f"sv-missing-{uuid.uuid4().hex[:12]}"
    await db[COLLECTION_RUNS].insert_one({"run_id": run_id})
    try:
        await ensure_schema_versions(db)  # must not raise
    finally:
        await db[COLLECTION_RUNS].delete_one({"run_id": run_id})
