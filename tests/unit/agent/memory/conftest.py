"""Shared fixtures for the agent-memory unit suite."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

# Same pepper convention as tests/unit/db/conftest.py — keeps API-key
# hashing deterministic for tests that exercise auth-adjacent code.
os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


@pytest_asyncio.fixture(autouse=True)
async def _ensure_agent_indexes():
    import db.connection as conn_mod
    from db.indexes import ensure_indexes

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        await ensure_indexes(database)
    finally:
        await conn_mod.close_connection()
    yield


@pytest_asyncio.fixture
async def db():
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        yield database
    finally:
        await conn_mod.close_connection()


@pytest.fixture
def unique_user_id():
    return f"u-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def other_user_id():
    return f"u-{uuid.uuid4().hex[:12]}"


class FakeEmbedder:
    """Stub embedder that returns a deterministic vector keyed by the text.

    Real Atlas Vector Search isn't needed for unit tests of `MongoDBStore`
    — what we want to verify is that the embedding round-trips correctly,
    not that mongot ranks similarity well. The fixed dimension matches
    the agent_memory_embeddings index `numDimensions`.
    """

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        # Deterministic toy embedding: a length-N vector seeded by hash.
        h = hash(text) & 0xFFFF
        return [float((h + i) % 17) / 17.0 for i in range(self.dim)]


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()
