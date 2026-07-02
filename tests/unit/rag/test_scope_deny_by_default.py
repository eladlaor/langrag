"""Deny-by-default scope tests (I5) — no Docker.

Two guarantees:
  - issue_key can NEVER mint a key without explicit non-empty scopes (fail-fast).
  - resolve_scopes only grants the empty-scopes->FULL legacy carve-out to keys
    created BEFORE the cutoff; a post-cutoff empty-scopes row resolves to NO
    scopes (not admin), and an explicit PODCAST_QUERY key never becomes FULL.
"""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF, RAGApiKeyScope
from custom_types.field_keys import RAGApiKeyKeys
from rag.auth.scopes import is_full_scope, resolve_scopes


def _key(scopes=None, created_at=None):
    rec = {RAGApiKeyKeys.KEY_ID: "k1"}
    if scopes is not None:
        rec[RAGApiKeyKeys.SCOPES] = scopes
    if created_at is not None:
        rec[RAGApiKeyKeys.CREATED_AT] = created_at
    return rec


def test_explicit_podcast_query_never_resolves_full():
    rec = _key(scopes=[str(RAGApiKeyScope.PODCAST_QUERY)], created_at=datetime.now(UTC))
    assert resolve_scopes(rec) == {str(RAGApiKeyScope.PODCAST_QUERY)}
    assert not is_full_scope(rec)


def test_legacy_empty_scopes_before_cutoff_is_full():
    before = RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF - timedelta(days=1)
    rec = _key(scopes=[], created_at=before)
    assert resolve_scopes(rec) == {str(RAGApiKeyScope.FULL)}


def test_empty_scopes_after_cutoff_denied_not_full():
    after = RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF + timedelta(days=1)
    rec = _key(scopes=[], created_at=after)
    assert resolve_scopes(rec) == set()
    assert not is_full_scope(rec)


def test_no_created_at_empty_scopes_keeps_full_backward_compat():
    # Records without a created_at (pre-existing tests / very old rows) keep the
    # FULL carve-out so nothing already-issued breaks.
    rec = _key(scopes=[])
    assert resolve_scopes(rec) == {str(RAGApiKeyScope.FULL)}


class _FakeCollection:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)

        class _R:
            inserted_id = "oid"

        return _R()


async def test_issue_key_requires_explicit_scopes(monkeypatch):
    from db.repositories.rag_api_keys import RAGApiKeysRepository

    repo = RAGApiKeysRepository.__new__(RAGApiKeysRepository)
    repo.collection = _FakeCollection()
    repo.collection_name = "rag_api_keys"

    with pytest.raises(ValueError):
        await repo.issue_key(name="x", owner="o", scopes=[])
    assert repo.collection.inserted == []  # nothing minted


async def test_issue_key_persists_explicit_scopes(monkeypatch):
    from db.repositories.rag_api_keys import RAGApiKeysRepository

    repo = RAGApiKeysRepository.__new__(RAGApiKeysRepository)
    repo.collection = _FakeCollection()
    repo.collection_name = "rag_api_keys"

    key_id, plaintext = await repo.issue_key(name="x", owner="o", scopes=[str(RAGApiKeyScope.PODCAST_QUERY)])
    assert plaintext.startswith("lrag_")
    assert repo.collection.inserted[0][RAGApiKeyKeys.SCOPES] == [str(RAGApiKeyScope.PODCAST_QUERY)]
