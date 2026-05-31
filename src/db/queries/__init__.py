"""Shared MongoDB aggregation builders.

Cross-collection helpers (e.g., `$rankFusion` pipelines) live here so they
can be reused without coupling the agent memory layer to RAG internals or
vice versa.
"""
