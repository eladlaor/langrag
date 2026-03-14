"""
Shared fixtures and utilities for subgraph tests.

NOTE: Tests that import from graphs.subgraphs modules require Docker environment
because graphs/__init__.py imports modules that depend on matrix_decryption.
Run in Docker: docker compose exec backend pytest tests/unit/subgraphs/
"""

import pytest


def _can_import_subgraphs():
    """Check if subgraph modules can be imported (requires matrix_decryption)."""
    try:
        # Try importing without triggering graphs/__init__.py
        import importlib.util
        spec = importlib.util.find_spec('graphs.subgraphs.link_enricher')
        return spec is not None
    except ImportError:
        return False


# Skip marker for Docker-required tests
requires_docker = pytest.mark.skipif(
    not _can_import_subgraphs(),
    reason="Requires Docker - graphs/__init__.py depends on matrix_decryption module"
)
