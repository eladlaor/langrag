"""DB-backed round-trip test for RunTracker diagnostics.

Lives under tests/unit/db/ so it inherits the real MongoDB `db` fixture and is
skipped automatically when MongoDB is unavailable. The pure-unit error-boundary
tests live in tests/unit/test_run_tracker.py.
"""

from __future__ import annotations

import uuid

from custom_types.field_keys import DbFieldKeys
from db.repositories.runs import RunsRepository
from db.run_tracker import RunTracker
from tests._helpers.mongo import requires_mongodb


@requires_mongodb
async def test_update_run_diagnostics_round_trip(db):
    """A diagnostic report persisted through the tracker reads back intact."""
    run_id = f"diag-test-{uuid.uuid4().hex[:12]}"
    runs_repo = RunsRepository(db)
    await runs_repo.create_run(
        run_id=run_id,
        data_source_name="langtalks",
        chat_names=["LangTalks Community"],
        start_date="2025-01-01",
        end_date="2025-01-02",
        config={},
    )

    tracker = RunTracker()
    tracker._initialized = True
    tracker._runs_repo = runs_repo

    report = {"summary": "round-trip", "stages": [{"name": "extract", "ok": True}]}
    persisted = await tracker.update_run_diagnostics(run_id, report)
    assert persisted is True

    stored = await runs_repo.find_one({DbFieldKeys.RUN_ID: run_id})
    assert stored is not None
    diag = stored[DbFieldKeys.DIAGNOSTIC_REPORT]
    assert diag["summary"] == "round-trip"
    assert DbFieldKeys.GENERATED_AT in diag

    await runs_repo.delete_one({DbFieldKeys.RUN_ID: run_id})
