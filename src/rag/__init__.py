"""
RAG (Retrieval-Augmented Generation) Module

Provides shared RAG infrastructure for conversing with content sources:
- Podcast transcripts
- Newsletters (Plan B)
- Chat messages (Future)

Architecture:
- sources/: Content source abstractions (Strategy pattern)
- chunking/: Chunking strategies per content type
- ingestion/: Source-agnostic ingest pipeline (extract -> chunk -> embed -> store)
- retrieval/: Vector search + reranking pipeline
- generation/: LLM answer generation with citations
- conversation/: Session and history management
- evaluation/: DeepEval quality evaluation
- transcription/: Audio transcription providers (Strategy pattern)
"""
