"""Integration test for the RAG eval corpus seeding script.

Verifies that seeding a clean DB produces a non-zero chunk count for both source
types and is idempotent (re-running does not duplicate chunks). Requires Docker
with MongoDB + an OpenAI key for embeddings; auto-skips otherwise, matching the
other tests/integration/rag conventions.

Run:
    docker compose exec app pytest tests/integration/rag/test_eval_seed.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

# See test_rest_refusal.py: defer app imports so the `tests/integration/rag`
# directory doesn't shadow the real top-level `rag` package at collection time.


def _ensure_src_rag_package() -> None:
    src = str(Path(__file__).resolve().parents[3] / "src")
    if sys.path and sys.path[0] != src:
        if src in sys.path:
            sys.path.remove(src)
        sys.path.insert(0, src)
    shadow = sys.modules.get("rag")
    if shadow is not None and "tests" in (getattr(shadow, "__file__", "") or ""):
        for name in [m for m in sys.modules if m == "rag" or m.startswith("rag.")]:
            del sys.modules[name]


async def _mongodb_available() -> bool:
    try:
        from db.connection import get_database

        db = await get_database()
        await db.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture
async def seeding(monkeypatch):
    _ensure_src_rag_package()

    if not await _mongodb_available():
        pytest.skip("MongoDB not available — run tests inside Docker")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — embeddings unavailable")

    # Import the script module by path (scripts/ is not a package on sys.path).
    import importlib.util

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "seed_rag_eval_corpus.py"
    spec = importlib.util.spec_from_file_location("seed_rag_eval_corpus", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from constants import COLLECTION_RAG_CHUNKS, ContentSourceType
    from custom_types.field_keys import RAGChunkKeys as Keys
    from db.connection import get_database

    db = await get_database()
    chunks = db[COLLECTION_RAG_CHUNKS]

    manifest = mod._load_manifest()
    fixture_source_ids = [e["source_id"] for e in manifest.get("newsletters", [])] + [e["source_id"] for e in manifest.get("podcasts", [])]

    # Clean any prior fixture chunks so the test starts from a known state.
    await chunks.delete_many({Keys.SOURCE_ID: {"$in": fixture_source_ids}})

    yield mod, db, chunks, Keys, ContentSourceType, fixture_source_ids

    await chunks.delete_many({Keys.SOURCE_ID: {"$in": fixture_source_ids}})


class TestEvalSeed:
    async def test_seed_produces_chunks_for_both_source_types(self, seeding):
        mod, db, chunks, Keys, ContentSourceType, _ = seeding

        totals = await mod.seed_corpus(force_refresh=True)

        assert totals[str(ContentSourceType.NEWSLETTER)] > 0
        assert totals[str(ContentSourceType.PODCAST)] > 0

        nl_in_db = await chunks.count_documents({Keys.CONTENT_SOURCE: str(ContentSourceType.NEWSLETTER)})
        pc_in_db = await chunks.count_documents({Keys.CONTENT_SOURCE: str(ContentSourceType.PODCAST)})
        assert nl_in_db > 0
        assert pc_in_db > 0

    async def test_seed_is_idempotent(self, seeding):
        mod, db, chunks, Keys, _, fixture_source_ids = seeding

        await mod.seed_corpus(force_refresh=True)
        count_after_first = await chunks.count_documents({Keys.SOURCE_ID: {"$in": fixture_source_ids}})

        # Second run without force_refresh must skip — no duplication.
        await mod.seed_corpus(force_refresh=False)
        count_after_second = await chunks.count_documents({Keys.SOURCE_ID: {"$in": fixture_source_ids}})

        assert count_after_second == count_after_first
