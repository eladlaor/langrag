# Changelog

## v1.8.0

- Concurrency: fixed non-atomic `asyncio.Lock` initialization across `connection.py`, `graph.py`, `checkpointer.py` (module-level init)
- Rate limiting applied to newsletter-generation and batch endpoints
- New constants: `DeliveryResultKeys`, `OutputPathKeys`, `WorkerResultKeys` — replaced 20+ hardcoded string literals
- Architecture: extracted `build_orchestrator_state()` factory; replaced `count_documents` with `find_one` for existence checks
- Removed unused `DiscussionRanker` class
- New deterministic newsletter-assembler module for metadata assembly

## v1.7.3
- Update default Anthropic model from Claude Sonnet 4.5 to Sonnet 4.6.

## v1.7.2
- Fix checkpointer bug: improved error handling and connection management in async SQLite checkpointer.

## v1.7.0
- LangGraph graph state checkpointing with AsyncSqliteSaver. Lazy async graph compilation, Docker volume mount for checkpoint persistence, integrated across orchestrator, scheduler, and batch worker.

## v1.6.5
- Email notification HTML template extracted to standalone file with template rendering. Expanded docstrings for field_keys and state_keys modules. Emoji-free log messages across decryption strategies and Beeper extractor.

## v1.6.4
- Async consistency: migrated requests to httpx, converted sync methods to async in Beeper extractor, discussion ranker, LinkedIn draft creator, and web searcher.

## v1.6.3
- Typo corrections (e.g., disussion to discussion), timezone.utc to UTC modernization, unused import cleanup across 53 files in src, tests, and CLI.

## v1.6.2
- DeepEval newsletter RAG test suite: 46 unit tests and 50 integration tests covering markdown chunking, newsletter source extraction, evaluation metrics, and golden dataset validation.

## v1.6.1
- Propagate force_refresh_extraction parameter to Beeper extractor for cache bypass support.

## v1.6.0
- RAG newsletter conversation: chat with past newsletters using retrieval-augmented generation.

## v1.5.0
- English newsletter rendering support: generate and render newsletters in English with Substack-compatible HTML output.

## v1.4.0
- RAG podcast conversation: ingest podcast transcripts, chunk, embed, and enable conversational Q&A over podcast content.

## v1.3.0
- Custom SLM: enhanced Ollama-based message pre-filtering with custom classifier configuration.

## v1.2.0
- Translation cache for avoiding redundant translation API calls. Poll message extraction and rendering support.

## v1.1.1
- Updated README: image extraction pipeline documentation, reply correlation section, reduced hardcoded model references.
- Updated pipeline animation and static diagram to include Extract Images and Associate Images stages.

## v1.1.0
  - Image analysis pipeline: extract, decrypt, and describe images from WhatsApp messages using vision models.
  - Images are now associated with their discussions and included as context in the relevant llm calls.
  - Expanded SLM classifier configuration options, as preparation for an upcoming fine-tuned SLM enhancement.  

## v1.0.0
  - Squashed first public release.
