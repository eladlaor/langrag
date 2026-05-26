# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.11.0] - 2026-05-26

### Added
- Per-document `schema_version` stamp on persisted MongoDB documents (`runs`, `discussions`, `messages`, `newsletters`, `rag_chunks`) with matching `CURRENT_SCHEMA_VERSION_*` constants in `src/constants.py` and Pydantic schemas (`NewsletterDocument`, `RAGChunkDocument`) added for the formerly raw-dict collections. No migration logic yet; the stamp enables future lazy migration.
- `RAGEmbeddingSettings` config section (`RAG_EMBEDDING_MODEL`, `RAG_EMBEDDING_DIMENSIONS`) and `EmbeddingSettings.output_dimensions` for A/B testing OpenAI's `dimensions` parameter (Matryoshka truncation) on the RAG ingestion/retrieval paths without touching discussion embeddings. Switching dimensions requires a full re-ingest because the vector index stores `numDimensions` at build time.
- Startup fail-fast validation that the configured RAG embedding dimensions match the active `rag_chunk_embeddings_v2` index; mismatched dims would silently break HNSW recall.
- `RAGSettings.vector_search_num_candidates_multiplier` (default 15) controlling the vector-only retrieval `numCandidates` multiplier; raised from the previous hardcoded 10 to widen the HNSW candidate pool.

### Changed
- Newsletter scheduler replaced its every-minute discovery poll with a MongoDB change stream on `scheduled_newsletters`. APScheduler now holds one `DateTrigger` job per enabled schedule, keyed by `schedule_id`, and fires at the exact `next_run`; the change-stream watcher keeps the in-memory job set in sync with inserts/updates/deletes. Fail-fast on stream loss with a bounded reconcile-and-retry.
- Lexical leg of the hybrid `$rankFusion` retrieval now pushes `content_source` and `source_date_*` clauses into `$search.compound.filter` instead of a downstream `$match`, so mongot prunes non-matching docs before Lucene scoring.
- LangGraph checkpointer migrated from `AsyncSqliteSaver` (local SQLite file) to `MongoDBSaver` (collections `checkpoints` and `checkpoint_writes` in the main MongoDB database). Consolidates all durable state into a single engine, enables horizontal scaling (checkpoints shared across replicas), and unifies backup. Requires `langgraph-checkpoint-mongodb>=0.4.0`.

### Removed
- Legacy compound TEXT index on `discussions.(title, nutshell)` and the dead `$text` fallback path in `/api/search/discussions`. Vector search is now the only path; embedding failures surface as a real 503 instead of silently degrading. `ensure_indexes()` drops the legacy text index idempotently on startup for existing deployments.
- `DiscussionsRepository.search_discussions()` (legacy `$text` query, no remaining callers after the fallback removal).
- Dependency on `langgraph-checkpoint-sqlite`.
- `CHECKPOINTER_SQLITE_PATH` env var (replaced by `CHECKPOINTER_DB_NAME`, `CHECKPOINTER_CHECKPOINT_COLLECTION`, `CHECKPOINTER_WRITES_COLLECTION`, `CHECKPOINTER_TTL_SECONDS`). Existing SQLite checkpoint files under `data/checkpoints/` are no longer read; safe to delete.


## [1.10.0] - 2026-05-21

### Changed
- LangTalks newsletter prompt: explicit attribution rules suppress internal `user_<N>` identifiers from rendered output while preserving them in the LLM input so multi-speaker context is retained. Hebrew and English neutral attribution phrases are spelled out in `LANGTALKS_NEWSLETTER_PROMPT` and across the three worth-mentioning templates; applies to both per-chat and consolidated flows.
- Changelog consolidated to a single root-level `CHANGELOG.md` in Keep a Changelog format; the prior `knowledge/CHANGELOG.md` and `knowledge/changelog/` archive removed.

### Added
- `tests/unit/test_langtalks_prompt_attribution.py`: pins the attribution rule presence across languages and guards against regressions that would drop `sender_id` from the model payload.

## [1.9.0] - 2026-05-02

### Added
- Date-aware RAG retrieval: every chunk tagged with `source_date_start` / `source_date_end`; `$vectorSearch` accepts date filters; answers carry mandatory `[date: ...]` citations; out-of-range queries are refused.
- MCP server exposing `rag_query`, `rag_search`, and `list_rag_sources` over stdio and HTTP/SSE.
- Eval gate with 50 golden cases and three custom metrics, wired into CI for changes under `src/rag/**`.
- nginx HTTPS configuration and certbot scaffolding for `langrag.ai` and `mcp.langrag.ai`.

### Changed
- `/api/rag/*` endpoints gated behind API key auth with slowapi rate limits.

## [1.8.0] - 2026-04-23

### Added
- `newsletter_assembler` module consolidating final newsletter composition.

### Changed
- Pipeline hardening across hot paths: constants enforcement, concurrency fixes, removal of the legacy `discussion_ranker` module in favor of MMR-based reranking.

## [1.7.3] - 2026-04-20

### Changed
- Default Anthropic model upgraded from Sonnet 4.5 to Sonnet 4.6.

## [1.7.2] - 2026-04-20

### Fixed
- Checkpointer bug surfaced after the v1.7.0 SQLite persistence rollout.

## [1.7.1] - 2026-04-18

### Changed
- README refresh.

## [1.7.0] - 2026-04-18

### Added
- LangGraph state checkpointing via `AsyncSqliteSaver`, with lazy async graph compilation and a Docker volume mount for checkpoint persistence; integrated across the orchestrator, scheduler, and batch worker.

## [1.6.5] - 2026-04-18

### Changed
- Email notification HTML extracted to a standalone template with rendering layer.
- Expanded docstrings for `field_keys` and `state_keys` modules.
- Emoji-free log messages across decryption strategies and the Beeper extractor.

## [1.6.4] - 2026-04-18

### Changed
- Async consistency pass: migrated `requests` to `httpx`, converted sync paths to async in the Beeper extractor, discussion ranker, LinkedIn draft creator, and web searcher.

## [1.6.3] - 2026-04-18

### Fixed
- Typo corrections (e.g., `disussion` → `discussion`), `timezone.utc` modernized to `UTC`, and unused imports cleaned up across 53 files in `src`, `tests`, and CLI.

## [1.6.2] - 2026-04-18

### Added
- DeepEval newsletter RAG test suite: 46 unit tests and 50 integration tests covering markdown chunking, newsletter source extraction, evaluation metrics, and golden dataset validation.

## [1.6.1] - 2026-04-18

### Fixed
- `force_refresh_extraction` parameter propagated to the Beeper extractor to enable cache bypass.

## [1.6.0] - 2026-04-15

### Added
- RAG newsletter conversation: retrieval-augmented Q&A over past newsletters.

## [1.5.0]

### Added
- English newsletter rendering with Substack-compatible HTML output.

## [1.4.0]

### Added
- RAG podcast conversation: ingest podcast transcripts, chunk, embed, and enable conversational Q&A over podcast content.

## [1.3.0]

### Added
- Custom SLM: Ollama-based message pre-filtering with configurable classifier.

## [1.2.0]

### Added
- Translation cache to avoid redundant translation API calls.
- Poll message extraction and rendering.

## [1.1.1]

### Changed
- README expanded with image extraction pipeline documentation and reply correlation section; reduced hardcoded model references.
- Pipeline animation and static diagram updated to include Extract Images and Associate Images stages.

## [1.1.0]

### Added
- Image analysis pipeline: extract, decrypt, and describe WhatsApp images using vision models; images associated with their parent discussion and included as context in downstream LLM calls.
- Expanded SLM classifier configuration in preparation for a fine-tuned SLM.

## [1.0.0]

### Added
- Initial public release.

[Unreleased]: https://github.com/eladlaor/langrag/compare/v1.11.0...HEAD
[1.11.0]: https://github.com/eladlaor/langrag/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/eladlaor/langrag/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/eladlaor/langrag/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/eladlaor/langrag/compare/v1.7.3...v1.8.0
[1.7.3]: https://github.com/eladlaor/langrag/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/eladlaor/langrag/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/eladlaor/langrag/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/eladlaor/langrag/compare/v1.6.5...v1.7.0
[1.6.5]: https://github.com/eladlaor/langrag/compare/v1.6.4...v1.6.5
[1.6.4]: https://github.com/eladlaor/langrag/compare/v1.6.3...v1.6.4
[1.6.3]: https://github.com/eladlaor/langrag/compare/v1.6.2...v1.6.3
[1.6.2]: https://github.com/eladlaor/langrag/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/eladlaor/langrag/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/eladlaor/langrag/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/eladlaor/langrag/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/eladlaor/langrag/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/eladlaor/langrag/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/eladlaor/langrag/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/eladlaor/langrag/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/eladlaor/langrag/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/eladlaor/langrag/releases/tag/v1.0.0
