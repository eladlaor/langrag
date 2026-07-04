"""Unit tests for the embedding-dims startup fail-fast (db.indexes).

Regression for the 2026-07-04 incident: the app booted healthy with a 3072-dim
config against a 1536-dim vector index because the mongot-unavailability
tolerance swallowed the mismatch RuntimeError as a warning. The mismatch now
raises a dedicated EmbeddingDimensionMismatchError that the tolerant except
blocks re-raise.
"""

import pytest

from custom_types.exceptions import ConfigurationError, EmbeddingDimensionMismatchError
from db.indexes import _extract_vector_index_dimensions, _validate_embedding_dims_against_index


def _index_info(dims: int) -> dict:
    return {
        "name": "rag_chunk_embeddings_v2",
        "latestDefinition": {
            "fields": [
                {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"},
                {"type": "filter", "path": "content_source"},
            ]
        },
    }


def test_extract_dimensions_from_latest_definition():
    assert _extract_vector_index_dimensions(_index_info(1536)) == 1536


def test_extract_dimensions_handles_definition_key():
    info = {"definition": _index_info(3072)["latestDefinition"]}
    assert _extract_vector_index_dimensions(info) == 3072


def test_extract_dimensions_none_when_no_vector_field():
    assert _extract_vector_index_dimensions({"latestDefinition": {"fields": [{"type": "filter", "path": "x"}]}}) is None


def test_mismatch_raises_dedicated_error(monkeypatch):
    from config import get_settings

    configured = get_settings()
    index_dims = 1536 if _configured_dims(configured) != 1536 else 3072
    with pytest.raises(EmbeddingDimensionMismatchError):
        _validate_embedding_dims_against_index(index_dims)


def test_mismatch_error_is_a_configuration_error():
    # The tolerant except blocks in indexes.py re-raise on this exact type;
    # it must stay a ConfigurationError subclass so operators can catch broadly.
    assert issubclass(EmbeddingDimensionMismatchError, ConfigurationError)


def test_matching_dims_pass():
    from config import get_settings

    _validate_embedding_dims_against_index(_configured_dims(get_settings()))


def test_unknown_index_dims_skips_validation():
    _validate_embedding_dims_against_index(None)


def _configured_dims(settings) -> int:
    if settings.rag_embedding.dimensions is not None:
        return settings.rag_embedding.dimensions
    return settings.embedding.output_dimensions
