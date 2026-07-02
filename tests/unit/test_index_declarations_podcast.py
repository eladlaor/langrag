"""Index-declaration tests for the podcast-MCP public lane (no Docker).

Asserts, at the definition level:
  - the `podcast_slug` filter is declared on both the vector-search and lexical
    Atlas Search index builders (mirroring data_source_name), so
    search_podcasts(podcast=<slug>) can pre-filter at mongot level.
  - the podcast_api_consumers collection has its expected btree indexes
    (unique email, sparse token-hash, sparse key_id) and NO TTL that would
    delete a verified consumer record.
"""

import inspect

from custom_types.field_keys import RAGChunkKeys
from db import indexes


def test_vector_index_declares_podcast_slug_filter():
    src = inspect.getsource(indexes._ensure_vector_search_index)
    assert "RAGChunkKeys.PODCAST_SLUG" in src or f'"{RAGChunkKeys.PODCAST_SLUG}"' in src


def test_lexical_index_declares_podcast_slug_mapping():
    src = inspect.getsource(indexes._ensure_lexical_search_index)
    assert "RAGChunkKeys.PODCAST_SLUG" in src or f'"{RAGChunkKeys.PODCAST_SLUG}"' in src


def test_podcast_api_consumers_index_block():
    block = indexes.INDEXES["podcast_api_consumers"]
    keys_lists = [tuple(k for k, _ in idx["keys"]) for idx in block]

    assert ("email",) in keys_lists
    # unique email
    email_idx = next(i for i in block if [k for k, _ in i["keys"]] == ["email"])
    assert email_idx.get("unique") is True

    assert ("verification_token_hash",) in keys_lists
    assert ("key_id",) in keys_lists

    # No TTL on any index (would delete verified consumer records).
    for idx in block:
        assert "expireAfterSeconds" not in idx
