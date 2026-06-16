"""
Integration tests for live date grounding.

These exercise the part the offline gate cannot: deriving each citation's TRUE
source date from the source-of-truth (the newsletters MongoDB document, the podcast
filename) independently of whatever date the chunk stored, then scoring it with
DateGroundingMetric. This is what catches ingestion-time date corruption — a chunk
stamped with the wrong date passes every other date metric but fails here.

Requires Docker with MongoDB running; skipped otherwise.

Run:
    docker compose exec app pytest tests/integration/rag/test_date_grounding.py -v
"""

import uuid

import pytest

from constants import (
    COLLECTION_NEWSLETTERS,
    ContentSourceType,
    NewsletterVersionType,
)
from custom_types.field_keys import DbFieldKeys, NewsletterStructureKeys

_TRUE_START = "2025-03-01"
_TRUE_END = "2025-03-14"
_TEST_NL_ID = f"test_grounding_{uuid.uuid4().hex[:8]}"

_TEST_NEWSLETTER_DOC = {
    DbFieldKeys.NEWSLETTER_ID: _TEST_NL_ID,
    DbFieldKeys.DATA_SOURCE_NAME: "langtalks",
    DbFieldKeys.START_DATE: _TRUE_START,
    DbFieldKeys.END_DATE: _TRUE_END,
    DbFieldKeys.CHAT_NAME: "LangTalks Community",
    DbFieldKeys.DESIRED_LANGUAGE: "english",
    DbFieldKeys.NEWSLETTER_TYPE: "per_chat",
    DbFieldKeys.STATUS: "completed",
    DbFieldKeys.VERSIONS: {
        str(NewsletterVersionType.TRANSLATED): {
            NewsletterStructureKeys.MARKDOWN_CONTENT: "## Discussion\n\nContent.",
        },
    },
}


async def _mongodb_available() -> bool:
    try:
        from db.connection import get_database

        db = await get_database()
        await db.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture
async def seed_newsletter():
    if not await _mongodb_available():
        pytest.skip("MongoDB not available — run inside Docker")
    from db.connection import get_database

    db = await get_database()
    coll = db[COLLECTION_NEWSLETTERS]
    await coll.insert_one(_TEST_NEWSLETTER_DOC.copy())
    yield _TEST_NL_ID
    await coll.delete_many({DbFieldKeys.NEWSLETTER_ID: _TEST_NL_ID})


@pytest.mark.asyncio
async def test_resolves_true_newsletter_date_from_source_of_truth(seed_newsletter):
    """The resolver reads start_date off the newsletter doc, not the citation."""
    from rag.evaluation.date_grounding import resolve_true_source_date

    # The citation's stored date is deliberately WRONG; the resolver must ignore it
    # and return the true date from the newsletters collection.
    citation = {
        "source_type": str(ContentSourceType.NEWSLETTER),
        "source_id": seed_newsletter,
        "source_date_start": "2024-01-01",  # corrupted — must not be trusted
    }
    true_date = await resolve_true_source_date(citation)
    assert true_date is not None
    assert true_date.date().isoformat() == _TRUE_START


@pytest.mark.asyncio
async def test_grounding_metric_catches_corrupted_date_live(seed_newsletter):
    """End-to-end: a citation whose stored date disagrees with the true source date
    fails DateGroundingMetric once the live oracle supplies ground truth."""
    from rag.evaluation.custom_metrics import DateGroundingMetric
    from rag.evaluation.date_grounding import build_expected_source_dates

    citations = [
        {
            "source_type": str(ContentSourceType.NEWSLETTER),
            "source_id": seed_newsletter,
            "source_date_start": "2024-01-01",  # corrupted
        }
    ]
    expected = await build_expected_source_dates(citations)
    assert expected.get(seed_newsletter) == _TRUE_START

    from types import SimpleNamespace

    case = SimpleNamespace(
        actual_output="",
        additional_metadata={"citations": citations, "expected_source_dates": expected},
    )
    metric = DateGroundingMetric()
    assert metric.measure(case) == 0.0
    assert metric.success is False


@pytest.mark.asyncio
async def test_grounding_metric_passes_when_stored_matches_true(seed_newsletter):
    from rag.evaluation.custom_metrics import DateGroundingMetric
    from rag.evaluation.date_grounding import build_expected_source_dates

    citations = [
        {
            "source_type": str(ContentSourceType.NEWSLETTER),
            "source_id": seed_newsletter,
            "source_date_start": _TRUE_START,  # correct
        }
    ]
    expected = await build_expected_source_dates(citations)

    from types import SimpleNamespace

    case = SimpleNamespace(
        actual_output="",
        additional_metadata={"citations": citations, "expected_source_dates": expected},
    )
    metric = DateGroundingMetric()
    assert metric.measure(case) == 1.0
    assert metric.success is True


@pytest.mark.asyncio
async def test_unresolvable_source_is_skipped_not_failed(seed_newsletter):
    """A newsletter id with no document yields no ground truth; the citation is
    skipped (a corpus gap is not a grounding failure)."""
    from rag.evaluation.date_grounding import build_expected_source_dates

    citations = [
        {
            "source_type": str(ContentSourceType.NEWSLETTER),
            "source_id": "does_not_exist_in_db",
            "source_date_start": "2025-03-01",
        }
    ]
    expected = await build_expected_source_dates(citations)
    assert "does_not_exist_in_db" not in expected
