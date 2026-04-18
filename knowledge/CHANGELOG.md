# Changelog

## Table of Contents
- [2026-04-18: DeepEval newsletter RAG test suite](#2026-04-18-deepeval-newsletter-rag-test-suite)
- [2026-04-18: Codebase Audit (B+ 82/100) & force_refresh_extraction Bug Fix](#2026-04-18-codebase-audit-b-82100--force_refresh_extraction-bug-fix)
- [2026-04-15: RAG Newsletter Conversation (Plan B)](#2026-04-15-rag-newsletter-conversation-plan-b)
- [2026-04-08: Overlap Extraction Cache & Sender Map Persistence (Phases 2-3)](#2026-04-08-overlap-extraction-cache--sender-map-persistence-phases-2-3)
- [2026-04-06: Per-Message Translation Cache (Phase 1 - Incremental Caching)](#2026-04-06-per-message-translation-cache-phase-1---incremental-caching)
- [2026-03-29: Image-to-Discussion Association (Phase 6)](#2026-03-29-image-to-discussion-association-phase-6)
- [2026-03-17: WhatsApp Image Extraction & Vision Understanding](#2026-03-17-whatsapp-image-extraction--vision-understanding)
- [2026-02-04: UI and SSE Event System Improvements](#2026-02-04-ui-and-sse-event-system-improvements)
- [2026-02-03: SLM Integration Phase 1 (Message Pre-filtering)](#2026-02-03-slm-integration-phase-1-message-pre-filtering)
- [2026-02-02: Newsletter Flow Improvements](#2026-02-02-newsletter-flow-improvements)
- [2026-01-07: Minor Code Cleanups and Bug Fixes](#2026-01-07-minor-code-cleanups-and-bug-fixes)
- [2026-01-05: Code Quality Improvements (Audit Follow-up)](#2026-01-05-code-quality-improvements-audit-follow-up)
- [2025-12-27: LangGraph 1.0 Migration (Native Async Nodes)](#2025-12-27-langgraph-10-migration-native-async-nodes)
- [2025-12-20: API Layer Restructuring](#2025-12-20-api-layer-restructuring)
- [2025-12-19: Beeper Setup Scripts Cleanup](#2025-12-19-beeper-setup-scripts-cleanup)
- [2025-12-19: CLI Tool Implementation](#2025-12-19-cli-tool-implementation)
- [2025-12-13: Newsletter Format Plugin System](#2025-12-13-newsletter-format-plugin-system)
- [2025-12-13: OpenAI Batch API Implementation](#2025-12-13-openai-batch-api-implementation)
- [2025-12-13: Intra-Newsletter Discussion Merging](#2025-12-13-intra-newsletter-discussion-merging)
- [2025-12-12: Anti-Repetition System](#2025-12-12-anti-repetition-system)
- [2025-12-06: Fail-Fast Error Handling Improvements](#2025-12-06-fail-fast-error-handling-improvements)
- [2025-12-06: Worth Mentioning Enhancement](#2025-12-06-worth-mentioning-enhancement)

---

## 2026-04-18: DeepEval newsletter RAG test suite

**What Changed:**
- Added 46 unit tests covering MarkdownChunker, NewsletterSource, DeepEval evaluator, and metrics factory
- Added 50 integration tests: newsletter ingestion pipeline (5) and golden dataset DeepEval evaluation (45 parametrized across 15 Q&A cases x 3 test types: retrieval, topic coverage, DeepEval metrics)
- Integration tests auto-skip without Docker; golden dataset loading is failure-safe

**Why:**
- Newsletter RAG production code (Plan B) shipped with 0% test coverage — this brings the DeepEval integration and newsletter-specific code to full test coverage
- Golden dataset tests establish the framework for collecting baseline quality scores and tuning thresholds

---

## 2026-04-18: Codebase Audit (B+ 82/100) & force_refresh_extraction Bug Fix

**What Changed:**
- Full codebase audit conducted — graded B+ (82/100). Full report: `knowledge/audits/AUDIT_2026_04_18.md`
- Bug fix: `force_refresh_extraction` was not propagated from graph state to the Beeper extractor's internal MongoDB cache check (`src/graphs/single_chat_analyzer/graph.py:248`). The `@with_cache_check` decorator bypassed the file-level cache, but the extractor's `kwargs.get("force_refresh", False)` always defaulted to `False`.

**Why:**
- Audit: periodic code health assessment to identify architectural risks and prioritize improvements.
- Bug fix: discovered during newsletter generation for AIL and AI Transformation Guild communities — stale empty extraction cache entries were being served despite `force_refresh_extraction: true`.

**Key audit findings (top 3):**
1. Sync `requests` blocking async event loop in `beeper.py` — production performance risk
2. No production checkpointer for LangGraph workflows — no crash recovery
3. `beeper.py` at 1504 lines is a God class needing decomposition

---

## 2026-04-15: RAG Newsletter Conversation (Plan B)

**What Changed:**

Implemented newsletter-specific RAG content source and ingestion pipeline (Plan B of the RAG conversation feature). Newsletters stored in MongoDB can now be chunked, embedded, and queried alongside podcast content.

**New Files:**
- `src/rag/sources/newsletter_source.py` -- Newsletter content source (reads from MongoDB `newsletters` collection, selects best version, delegates to MarkdownChunker)
- `src/rag/chunking/markdown_chunker.py` -- Section-aware markdown chunking (splits on headers, preserves discussion boundaries, classifies section types)
- `tests/golden_datasets/newsletters_v1.json` -- 15 Q&A golden dataset for newsletter RAG evaluation

**Modified Files:**
- `src/constants.py` -- Added `ROUTE_RAG_CHAT`, `ROUTE_RAG_INGEST_NEWSLETTERS`, `ROUTE_RAG_SOURCES_NEWSLETTERS`
- `src/custom_types/api_schemas.py` -- Added `RAGChatResponse`, `RAGCitationResponse`, `RAGNewsletterIngestRequest`
- `src/api/rag_conversation.py` -- Added 3 endpoints: `POST /rag/chat` (non-streaming), `POST /rag/ingest/newsletters`, `GET /rag/sources/newsletters`
- `ui/frontend/src/components/rag/CitationCard.tsx` -- Newsletter-specific citation rendering (date range, section title, section type badges)
- `ui/frontend/src/constants/rag.ts` -- Added new API routes

**Why:**
- Newsletter content was already in MongoDB but not searchable via RAG
- Non-streaming chat endpoint enables CLI/agent interaction without SSE
- Cross-source queries (podcast + newsletter) work out of the box via the shared retrieval pipeline

---

## 2026-04-08: Overlap Extraction Cache & Sender Map Persistence (Phases 2-3)

**What Changed:**

Completed the remaining two phases of the incremental caching plan, enabling efficient date range extension for newsletter generation.

**Phase 2: Overlap-Aware Extraction Cache**

When the exact cache key misses (different date range), the system now checks for overlapping cached extractions. Three scenarios are handled:

1. **Superset cache hit**: A cached extraction fully contains the requested range (e.g., cached Mar 15-Apr 10, requested Mar 19-Apr 6). Messages are filtered by timestamp from cache — no Beeper API call needed.
2. **Partial overlap**: Messages from overlapping caches are collected and merged with freshly extracted messages (deduplicated by `event_id`).
3. **No overlap**: Falls through to full extraction (existing behavior).

Files modified:
- `src/db/repositories/extraction_cache.py` — Added `get_overlapping_extractions()` and `_normalize_chat_name()`, plus `chat_name_normalized` field in stored documents
- `src/core/ingestion/extractors/beeper.py` — Added overlap-aware cache lookup (superset detection + partial overlap merge) before the exact-match fallback
- `src/db/indexes.py` — Added `chat_name_normalized` compound index on `extraction_cache`

**Phase 3: Sender Map Persistence**

Sender anonymization maps (`@alice:beeper.com` -> `user_1`) are now persisted to MongoDB. When preprocessing runs again (different date range, same chat), the same user always gets the same anonymized ID.

1. **New Repository** (`src/db/repositories/sender_map.py`): `SenderMapRepository` with `get_sender_map` and `upsert_sender_map` methods.
2. **Modified Preprocessing** (`src/core/ingestion/preprocessors/whatsapp.py`): `_parse_and_standardize_raw_whatsapp_messages_with_stats` is now async, loads sender map from MongoDB at start, persists updated map at end. Also fixed inter-chunk sender map propagation (sender map now fed back between chunks).
3. **New Constant** (`src/constants.py`): `COLLECTION_SENDER_MAPS`.
4. **New Index** (`src/db/indexes.py`): Unique compound index on `(data_source_name, chat_name)`.

**Plan:** `knowledge/plans/INCREMENTAL_CACHING_PLAN.md`

---

## 2026-04-06: Per-Message Translation Cache (Phase 1 - Incremental Caching)

**What Changed:**

Added per-message translation caching to MongoDB so that extending a newsletter date range (e.g., Mar 19-Apr 4 to Mar 19-Apr 6) only translates the new messages. Previously, ALL messages were re-sent to OpenAI even if 95% were already translated in a prior run.

**Why:** Common workflow is to generate a newsletter, then extend the date range by a few days before sending. Without caching, every extension re-translates all messages at full cost.

1. **New Repository** (`src/db/repositories/translation_cache.py`): `TranslationCacheRepository` with bulk get/store operations. Keyed by `(matrix_event_id, target_language)` with SHA256 content hash for edit detection and TTL-based expiration.

2. **Modified Translation Flow** (`src/core/ingestion/preprocessors/whatsapp.py`): `_translate_whatsapp_group_chat_messages` now looks up cached translations before sending to OpenAI Batch API. Only uncached (or edited) messages are translated. Fresh translations are stored back to cache.

3. **New MongoDB Indexes** (`src/db/indexes.py`): Compound unique index on `(matrix_event_id, target_language)` and TTL index on `expires_at`.

4. **New Constants** (`src/constants.py`): `COLLECTION_TRANSLATION_CACHE`, `DEFAULT_TRANSLATION_CACHE_TTL_DAYS`.

5. **Config** (`src/config.py`): `translation_cache_ttl_days` setting (default 30 days).

6. **Graph Node** (`src/graphs/single_chat_analyzer/graph.py`): `translate_messages` node now passes `chat_name`, `data_source_name`, and `force_refresh_translation` to the translation method.

**Plan:** `knowledge/plans/INCREMENTAL_CACHING_PLAN.md` (Phase 2: extraction overlap cache, Phase 3: sender map persistence — not yet implemented).

---

## 2026-03-29: Image-to-Discussion Association (Phase 6)

**What Changed:**

New pipeline node `associate_images` added between `rank_discussions` and `generate_content` in the SingleChatAnalyzer graph. Maps extracted image descriptions to their parent discussions and injects them into the newsletter generation LLM prompt.

1. **Association Node** (`src/graphs/single_chat_analyzer/associate_images.py`):
   - Matches `ImageMetadata.message_id` to `Discussion.messages[].id`
   - Builds `discussion_id -> list[image descriptions]` map
   - Updates MongoDB `discussion_id` field on matched images (fail-soft)
   - Caps: `MAX_IMAGES_PER_DISCUSSION=3`, `MAX_IMAGES_TOTAL=15` (in `constants.py`)

2. **Image Context in LLM Prompts** (`src/custom_types/newsletter_formats/image_context.py`):
   - Shared `build_image_context_text()` utility appends IMAGE CONTEXT section to user message
   - Groups image descriptions by discussion title
   - All three format plugins (langtalks, mcp_israel, whatsapp) use it

3. **Data Threading**:
   - `image_discussion_map` added to `SingleChatState` and `SingleChatStateKeys`
   - Threaded through `generate_content` node -> `NewsletterContentGenerator` -> format `build_messages()`
   - `LlmInputKeys.IMAGE_DISCUSSION_MAP` constant for kwargs access

**Why:** Images were extracted and described but sat unused. This makes the newsletter LLM aware of visual content shared in discussions, enriching the generated summaries.

**Scope:** Per-chat newsletters only. Consolidated (cross-chat) newsletters do not yet receive image context.

---

## 2026-03-17: WhatsApp Image Extraction & Vision Understanding

**What Changed:**

New pipeline node `extract_images` added between `slm_prefilter` and `preprocess_messages` in the SingleChatAnalyzer graph. Extracts, downloads, persistently stores, and optionally describes (via vision LLM) images from WhatsApp messages.

1. **Foundation (Types, Config, Constants):**
   - `VisionSettings` in `config.py` with full environment variable support (`VISION_*` prefix)
   - `MatrixMessageType` enum in `constants.py` for `m.image`, `m.video`, etc.
   - `ImageMetadata` and `ImageExtractionStats` Pydantic models in `custom_types/common.py`
   - `ImageKeys` field key class in `custom_types/field_keys.py`
   - Image state keys in `SingleChatStateKeys` and `ParallelOrchestratorStateKeys`
   - `enable_image_extraction` API parameter in `PeriodicNewsletterRequest`

2. **Image Extraction from Raw Messages:**
   - `image_extractor.py`: Scans raw Matrix messages for `msgtype == "m.image"`, extracts mxc URLs, dimensions, mimetype, sender, timestamp
   - `image_downloader.py`: Downloads images from `mxc://` URLs via Matrix media endpoint with bounded concurrency

3. **Persistent Storage:**
   - `LocalMediaStorage` in `core/storage/media_storage.py`: S3-like path structure (`data/media/images/{source}/{chat}/{YYYY-MM}/`)
   - Docker volume mount added: `./data/media:/app/data/media`
   - `ImagesRepository` in `db/repositories/images.py`: MongoDB CRUD with deduplication by mxc_url

4. **Vision LLM Integration:**
   - `call_with_vision()` added to `LLMProviderInterface` (default: NotImplementedError)
   - OpenAI implementation using `detail: "low"` (85 tokens/image, ~$0.001/image with gpt-4.1-mini)
   - `image_describer.py`: Cached vision descriptions via `CacheService`

5. **Pipeline Integration:**
   - `extract_images_node` in `graphs/single_chat_analyzer/image_extraction.py`
   - Fail-soft: any exception logs and returns empty stats, pipeline continues
   - Double-gated: requires both `VISION_ENABLED=true` AND `enable_image_extraction=true` in request
   - Wired into graph: `slm_prefilter → extract_images → preprocess_messages`

**Why:** Images in WhatsApp groups carry significant informational value (screenshots, diagrams, tool demos) that was previously silently dropped. This enables image galleries, analytics, and enriched newsletter content.

**Files Created:** `image_extractor.py`, `image_downloader.py`, `media_storage.py`, `image_describer.py`, `images.py` (repo), `image_extraction.py` (node)

**Files Modified:** `config.py`, `constants.py`, `field_keys.py`, `common.py`, `api_schemas.py`, `state_keys.py`, `state.py` (single chat + orchestrator), `graph.py` (single chat + orchestrator), `interface.py`, `openai_provider.py`, `newsletter_gen.py`, `docker-compose.yml`, `.env.example`, `sse_events.py`, `api/sse/__init__.py`

---

## 2026-02-04: UI and SSE Event System Improvements

**What Changed:**

1. **SSE Robustness (Phase 1):**
   - Added exponential backoff reconnection (max 3 attempts, 2s initial delay)
   - Replaced simple `split('\n')` with proper SSE message parser using double newline (`\n\n`) boundary
   - Added 30s connection timeout detection with `lastEventTime` tracking
   - New `reconnecting` status in `WorkflowStatus` type

2. **Consolidation Progress Visibility (Phase 2):**
   - Added `@with_progress` decorators to 6 consolidation nodes in `consolidation_nodes.py`
   - New `ConsolidationProgress` interface in frontend types
   - Special `__consolidated__` chat name identifies consolidation events
   - New consolidation progress card in `ProgressTracker.tsx` between overall progress and per-chat cards
   - Handles `consolidation_started` and `consolidation_completed` event types

3. **Type Safety (Phase 3):**
   - Created `eventValidation.ts` with Zod schemas for SSE event validation
   - Runtime validation in `useNewsletterStream` - invalid events logged but don't crash
   - Added `zod` dependency to frontend

4. **UX Polish (Phase 4):**
   - RTL/LTR preference persisted in `localStorage` (RunsBrowser)
   - Auto-cleanup for stale progress queues (2h timeout, opportunistic on new queue creation)
   - Added `created_at` and `last_activity` timestamps to ProgressQueue

**Why Changed:**
- SSE connections could silently fail without recovery mechanism
- Consolidation phase (cross-chat merging) had no progress visibility in UI
- No runtime validation of SSE events - invalid events could cause UI errors
- User preferences weren't persisted across sessions
- Progress queues could accumulate without cleanup causing memory leaks

**Files Created:**
- `ui/frontend/src/utils/eventValidation.ts` - Zod schemas for SSE event validation

**Files Modified (Frontend):**
- `ui/frontend/src/hooks/useNewsletterStream.ts` - Reconnection logic, SSE parsing, consolidation handling, Zod validation
- `ui/frontend/src/components/ProgressTracker.tsx` - Consolidation progress card, reconnecting status
- `ui/frontend/src/components/PeriodicNewsletterForm.tsx` - Handle reconnecting status
- `ui/frontend/src/components/RunsBrowser.tsx` - localStorage persistence for direction preference
- `ui/frontend/src/types/index.ts` - Added `ConsolidationProgress`, `reconnecting` status
- `ui/frontend/package.json` - Added `zod` dependency

**Files Modified (Backend):**
- `src/graphs/multi_chat_consolidator/consolidation_nodes.py` - Added `@with_progress` decorators to 6 nodes
- `src/api/sse/node_decorators.py` - Updated `with_progress` to detect consolidation stages and use `__consolidated__` chat name
- `src/api/sse/progress_queue.py` - Added `created_at`, `last_activity`, `is_stale()`, `cleanup_stale_queues()`

**Usage:**
- SSE reconnection happens automatically on connection loss (up to 3 attempts)
- Consolidation progress appears when running multi-chat newsletters with `consolidate_chats=true`
- RTL/LTR toggle in RunsBrowser now remembers preference

**When Changed:** 2026-02-04

---

## 2026-02-03: SLM Integration Phase 1 (Message Pre-filtering)

**What Changed:**
- Added Ollama container to Docker Compose for local SLM inference
- Created SLM provider module (`src/core/slm/provider.py`) with OpenAI-compatible Ollama API client
- Implemented message classifier (`src/core/slm/classifier.py`) for KEEP/FILTER/UNCERTAIN classification
- Added `slm_prefilter` node to NewsletterGenerationGraph after extraction
- Created SLM schemas in `src/custom_types/slm_schemas.py` for type-safe classification
- Added SLM configuration to `src/config.py` (SLMSettings class)
- Updated `.env.example` with all SLM configuration options
- Added unit tests for provider and classifier

**Why Changed:**
- Reduce expensive OpenAI API calls by 15-30% by filtering low-quality messages early
- Local CPU-based inference via Ollama is essentially free after initial model download
- Fail-soft design: if SLM is unavailable, pipeline continues without filtering
- Fail-safe design: UNCERTAIN messages continue to LLM (never filter potentially valuable content)
- Easy rollback via `SLM_ENABLED=false` environment variable

**New Pipeline:**
```
extract → slm_prefilter → preprocess → translate → separate → rank → generate → enrich → translate_final
```

**Classification Logic:**
- **KEEP**: Technical discussions, questions, answers, announcements, resources (continues to LLM)
- **FILTER**: Spam, greetings only, emoji-only, promotional, off-topic (removed from pipeline)
- **UNCERTAIN**: Ambiguous content (continues to LLM - fail-safe)

**Files Created:**
- `src/core/slm/__init__.py` - Module exports
- `src/core/slm/provider.py` - OllamaProvider class with health check and completion API
- `src/core/slm/classifier.py` - MessageClassifier with batch classification and filtering helpers
- `src/custom_types/slm_schemas.py` - Type definitions (MessageClassification, SLMFilterStats, etc.)
- `src/graphs/single_chat_analyzer/slm_prefilter.py` - Pre-filter node for the graph
- `tests/unit/slm/__init__.py` - Test package
- `tests/unit/slm/test_slm_provider.py` - Provider unit tests
- `tests/unit/slm/test_slm_classifier.py` - Classifier unit tests

**Files Modified:**
- `docker-compose.yml` - Added Ollama service with resource limits (4GB RAM, health check)
- `src/config.py` - Added SLMSettings class with all configuration options
- `.env.example` - Added SLM configuration section
- `src/custom_types/__init__.py` - Exported SLM schemas
- `src/core/__init__.py` - Updated module docstring
- `src/graphs/single_chat_analyzer/graph.py` - Added slm_prefilter node and edge
- `src/graphs/single_chat_analyzer/state.py` - Added slm_filter_stats field
- `internal_knowledge/plans/SLM_INTEGRATION.md` - Updated task completion status
- `CLAUDE.md` - Added SLM integration documentation

**Configuration:**
```bash
# Enable SLM filtering (default: false)
SLM_ENABLED=true

# Ollama settings
SLM_BASE_URL=http://ollama:11434
SLM_MODEL=phi3:mini
SLM_CONFIDENCE_THRESHOLD=0.7

# Pull model (one-time, after docker compose up)
docker exec langtalks-ollama ollama pull phi3:mini
```

**Live Test Results** (2026-02-03):
- Classification accuracy: 77.8% (7/9 correct)
- Filter rate: 50% (exceeds 15-30% target)
- Correctly classified technical questions as KEEP
- Correctly filtered greetings, emoji-only, and spam
- Avg inference time: ~9s/message on CPU (acceptable for batch processing)

**Observability:**
- Langfuse spans for SLM classification
- Diagnostic messages for filter statistics
- Logging of filtered messages with reasons
- Filter stats in state for debugging

**Impact:**
- ✅ No breaking changes - SLM disabled by default
- ✅ Easy enable/disable via environment variable
- ✅ Fail-soft on SLM unavailability (pipeline continues)
- ✅ Fail-safe on uncertain classification (keeps messages)
- ✅ Live test shows 50% filter rate (exceeds 15-30% target)

**When Changed:** 2026-02-03

---

## 2026-02-02: Newsletter Flow Improvements

**What Changed:**
1. Anti-repetition prompt moved before ranking criteria with stronger emphasis, concrete examples, and nutshell summaries from previous newsletters
2. Worth mentioning quality: importance_score >= 5 filter, medium repetition filtered out, capped at 10 candidates, stronger prompt with bad/good examples
3. Ranking format-specific guidance: expanded langtalks/mcp format descriptions with priority topics
4. Cross-chat merge visibility: merged discussions show group badge in markdown and HTML output, SSE progress log for merge operations
5. Merge threshold lowered from 0.85 to 0.82 for "moderate" to catch vocabulary variations
6. State key constants refactoring: Replaced hardcoded state key strings with `RankerKeys.*` and `EnricherKeys.*` constants in subgraph files
7. Anti-repetition default increased from 5 to 8 previous newsletters

**Why Changed:**
- Anti-repetition was being ignored by ranking LLM due to section placement (after criteria)
- Worth mentioning had generic one-liners, overlaps with featured, and no quality floor
- "Relevance" was too vague for the LLM to prioritize correctly per community
- Users couldn't see which discussions were merged across groups
- 0.85 cosine threshold missed same-topic discussions using different vocabulary
- Hardcoded strings like `state["separate_discussions_file_path"]` were typo-prone and didn't benefit from IDE autocomplete
- 8 newsletters provides better anti-repetition coverage than 5

**Files Modified (State Key Constants):**
- `src/config.py`: Added `default_previous_newsletters_to_consider: 8` to RankingSettings
- `src/graphs/state_keys.py`: Added `ENABLE_MMR_DIVERSITY` and `MMR_LAMBDA` to DiscussionRankerStateKeys
- `src/graphs/subgraphs/discussions_ranker.py`: Refactored to use `RankerKeys.*` constants
- `src/graphs/subgraphs/link_enricher.py`: Refactored to use `EnricherKeys.*` constants
- `src/graphs/subgraphs/state.py`: Refactored builder functions to use constants
- `src/graphs/multi_chat_consolidator/consolidation_nodes.py`: Refactored ~85 hardcoded strings to use `OrchestratorKeys.*`, `RankerKeys.*`, `EnricherKeys.*`
- `src/graphs/multi_chat_consolidator/graph.py`: Refactored ~25 hardcoded strings to use `OrchestratorKeys.*`
- `src/graphs/multi_chat_consolidator/linkedin_draft_creator.py`: Refactored to use `OrchestratorKeys.*`

**When Changed:** 2026-02-02

---

## 2026-01-07: Minor Code Cleanups and Bug Fixes

**What Changed:**
- Removed unused `failed_chats` variable in `batch_worker.py`
- Added missing import `_get_tracker` in `newsletter_gen.py`
- Fixed web search bug: changed `google_results[:1]` to `google_results[:num_results]` in `search_manager.py`
- Clarified `source_documents` type comment in `common.py` (LlamaIndex Document objects)
- Added missing return type annotation `-> str` to `extract_messages()` in `beeper.py`

**Why Changed:**
- Code review identified unused variables and missing imports
- Web search was only processing 1 result instead of requested `num_results`
- Type annotations improve IDE support and code clarity
- Comment clarifications prevent confusion about object types

**Files Modified:**
- `src/background_jobs/batch_worker.py`: Removed unused `failed_chats` variable (line 251)
- `src/api/newsletter_gen.py`: Added missing `from db.run_tracker import _get_tracker` import
- `src/utils/tools/web_searcher/search_manager.py`: Fixed slice from `[:1]` to `[:num_results]` (line 21)
- `src/custom_types/common.py`: Updated source_documents comment for clarity (line 94)
- `src/core/ingestion/extractors/beeper.py`: Added return type `-> str` to `extract_messages()` method (line 969)

**Impact:**
- ✅ Cleaner code with no unused variables
- ✅ All imports properly declared
- ✅ Web search now respects num_results parameter
- ✅ Better type safety and documentation

---

## 2026-01-05: Code Quality Improvements (Audit Follow-up)

**What Changed:**
- Extracted duplicate validation logic into comprehensive `validate_newsletter_request()` helper
- Created `setup_output_directory()` helper function for DRY output directory setup
- Fixed bare `except:` block in SSE streaming (now `except Exception:`)
- Replaced inline string keys with `OrchestratorKeys` constants in `batch_worker.py`

**Why Changed:**
- Codebase audit identified validation duplication (~80 lines copied between endpoints)
- Bare `except:` blocks violate fail-fast principles and hide errors
- Inline string keys are typo-prone and don't benefit from IDE autocomplete
- Consolidating helpers into single source of truth prevents logic drift

**Files Modified:**
- `src/api/newsletter_gen.py`:
  - Expanded `validate_newsletter_request()` to include date validation, empty chat list check, output action validation
  - Added `setup_output_directory()` helper for directory creation and write permission testing
  - Simplified `generate_periodic_newsletter()` and `generate_periodic_newsletter_stream()` to use helpers
  - Fixed bare `except:` at SSE error handling to `except Exception:`
- `src/background_jobs/batch_worker.py`:
  - Added import of `ParallelOrchestratorStateKeys as OrchestratorKeys`
  - Replaced `"successful_chats"`, `"failed_chats"`, `"total_chats"`, `"chat_errors"` with `OrchestratorKeys.*` constants

**Lines Removed:**
- ~70 lines of duplicate validation code between two endpoints
- ~20 lines of duplicate output directory setup code

**Impact:**
- ✅ Single source of truth for validation logic
- ✅ Consistent error messages across endpoints
- ✅ Type-safe state key access in batch worker
- ✅ All files compile successfully
- ✅ No breaking changes to API contracts

---

## 2025-12-27: LangGraph 1.0 Migration (Native Async Nodes)

**What Changed:**
- Upgraded from LangGraph 0.6.7 (sync nodes) to LangGraph 1.0+ (native async nodes)
- Converted all 25+ graph nodes to `async def` functions with direct `await` calls
- Eliminated all sync wrapper functions (`*_sync()`) that used `run_async()` bridge
- Removed ~322 lines of sync wrapper code across 4 database modules
- Changed all graph invocations from `.invoke()` to `await .ainvoke()`
- Added proper `RunnableConfig` type annotations to all node config parameters
- Created dual-mode decorators that work with both sync and async functions

**Why This Migration:**
- **Root Cause**: Event loop conflicts when parallel LangGraph workers attempted MongoDB operations
- LangGraph 0.6.7 required synchronous nodes, but MongoDB used async Motor driver
- The `run_async()` bridge created new event loops per operation in ThreadPoolExecutor
- Motor's connection pool expected consistent event loop; parallel workers created multiple isolated loops
- Result: "different event loop" errors during parallel chat processing

**Architecture Before:**
```
FastAPI (uvloop)
  → LangGraph parallel workers (Send API) × N
    → Each worker: run_async() → new event loop in thread
      → Motor async operations → "different event loop" error
```

**Architecture After:**
```
FastAPI (uvloop)
  → LangGraph parallel workers (Send API) × N
    → Each worker: native async def → await db operations
      → Motor async operations → same event loop (OK)
```

**Files Deleted:**
- `src/db/async_utils.py` - Removed entirely (47 lines containing `run_async()` function)

**Files Modified - Database Layer:**
- `src/db/run_tracker.py` - Removed 12 sync wrapper functions (~180 lines)
- `src/db/batch_jobs.py` - Removed 7 sync wrapper functions (~65 lines)
- `src/db/cache.py` - Removed 2 sync wrapper functions (~30 lines)
- `src/db/__init__.py` - Rewritten for async-only exports

**Files Modified - Graph Nodes (25+ nodes across 5 graphs):**
- `src/graphs/single_chat_analyzer/graph.py` - 9 nodes converted to async
- `src/graphs/multi_chat_consolidator/graph.py` - 7 nodes converted to async
- `src/graphs/multi_chat_consolidator/consolidation_nodes.py` - 7 nodes converted to async
- `src/graphs/subgraphs/discussions_ranker.py` - 1 node converted to async
- `src/graphs/subgraphs/link_enricher.py` - 4 nodes converted to async

**Files Modified - Infrastructure:**
- `src/graphs/subgraphs/progress_tracker.py` - Dual-mode decorator support
- `src/api/newsletter_gen.py` - Graph invocations: `.invoke()` → `await .ainvoke()`
- `src/workers/batch_worker.py` - Fully async with direct manager calls

**Files Modified - Tests:**
- `tests/integration/mongodb/test_mongodb_persistence.py` - Async graph invocation
- `tests/integration/mongodb/test_newsletters_persistence.py` - Async graph invocation

**Key Patterns Introduced:**

1. **Native Async Nodes:**
```python
# Before (sync node with run_async bridge)
def translate_messages(state: SingleChatState, config: Optional[dict] = None) -> dict:
    store_messages_sync(messages)  # Used run_async() internally
    return {"translated_messages_file_path": path}

# After (native async node)
async def translate_messages(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    tracker = _get_tracker()
    await tracker.store_messages(messages)  # Direct async call
    return {"translated_messages_file_path": path}
```

2. **Direct Async Database Calls:**
```python
# Before
from db.run_tracker import store_messages_sync
store_messages_sync(run_id, messages)

# After
from db.run_tracker import _get_tracker
tracker = _get_tracker()
await tracker.store_messages(run_id, messages)
```

3. **Async Graph Invocation:**
```python
# Before
result = parallel_orchestrator_graph.invoke(state, config)

# After
result = await parallel_orchestrator_graph.ainvoke(state, config)
```

4. **Dual-Mode Decorators:**
```python
def with_logging(func):
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger.info(f"Starting {func.__name__}")
            result = await func(*args, **kwargs)
            return result
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # ... sync version
        return sync_wrapper
```

**Impact:**
- ✅ Eliminated all event loop conflicts in parallel workflows
- ✅ Removed ~322 lines of sync wrapper code
- ✅ Single event loop architecture (FastAPI → LangGraph → MongoDB)
- ✅ Better I/O concurrency for LLM + DB operations
- ✅ Cleaner code without `run_async()` bridges
- ✅ All graphs compile without warnings
- ✅ Proper `RunnableConfig` type annotations throughout

**Verification:**
```bash
# All graphs compile successfully
.venv/bin/python -c "from graphs.single_chat_analyzer.graph import newsletter_generation_graph; print('OK')"
.venv/bin/python -c "from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph; print('OK')"

# API imports successfully
.venv/bin/python -c "from api.newsletter_gen import router; print('OK')"

# No config type warnings
# All ainvoke methods available
```

---

## 2025-12-20: API Layer Restructuring

**What Changed:**
- Reorganized API routes from 4 flat files into a cleaner, intent-based structure
- Created `api/observability/` subpackage for system monitoring and historical data access
- Renamed `newsletters.py` → `newsletter_gen.py` for clearer naming
- Extracted batch job endpoints into dedicated `async_batch_orchestration.py`
- Eliminated duplicate endpoints and leaky abstraction of MongoDB routes

**Why This Restructuring:**
- **Violated Repository Pattern**: Old `mongodb.py` exposed database implementation details directly in the API
- **Confusing Organization**: Split by database technology (mongodb.py) rather than business capability
- **Duplicate Routes**: Both `runs.py` and `mongodb.py` had overlapping endpoints for querying run data
- **Poor Separation**: Newsletter generation, batch orchestration, and observability mixed together

**New Structure:**
```
src/api/
├── newsletter_gen.py              # Newsletter generation lifecycle (write operations)
├── async_batch_orchestration.py   # Background job management (async orchestration)
└── observability/
    ├── __init__.py                # Re-export routers
    ├── metrics.py                 # Prometheus metrics
    └── runs.py                    # Historical data access & analytics
```

**Organizational Principles:**
1. **User Intent, Not Database Structure**: Routes organized by what users want to accomplish, not by which database is used
2. **Observability as a Frame**: Treating historical data queries as part of system observability (logs, metrics, traces, runs)
3. **Repository Pattern**: MongoDB is now an implementation detail hidden behind the API, not exposed directly
4. **Clean Separation**: Newsletter creation vs async orchestration vs observability are distinct concerns

**Files Changes:**
- **Deleted**: `api/mongodb.py` (merged into `api/observability/runs.py`)
- **Deleted**: `api/metrics.py` (moved to `api/observability/metrics.py`)
- **Deleted**: `api/runs.py` (merged into `api/observability/runs.py`)
- **Renamed**: `api/newsletters.py` → `api/newsletter_gen.py`
- **Created**: `api/async_batch_orchestration.py` (extracted from newsletters.py)
- **Created**: `api/observability/` subpackage

**Route Changes:**
- **Removed duplicate routes**: `/api/mongodb/runs` merged with `/api/runs`
- **Backward compatibility**: MongoDB routes temporarily available at `/api/mongodb/*` but marked as deprecated
- **Cleaner tags**: OpenAPI tags now reflect purpose (`newsletter-generation`, `async-batch-orchestration`, `observability-runs`, `observability-metrics`)

**Impact:**
- ✅ No breaking changes to existing API clients
- ✅ MongoDB is now properly abstracted behind repository pattern
- ✅ Clearer API documentation with intent-based organization
- ✅ Easier to understand what each endpoint does and why it exists
- ⚠️ MongoDB routes at `/api/mongodb/*` are deprecated (will be removed in future release)

**Migration Path:**
- For API consumers: No changes needed, routes remain compatible
- For developers: Import from new locations (`from api.observability import runs_router`)
- Future: Remove deprecated `/api/mongodb/*` routes once all clients migrate

---

## 2025-12-19: Beeper Setup Scripts Cleanup

**What Changed:**
- Removed 4 experimental/redundant Beeper setup scripts from `ui/cli/beeper_setup/`
- Retained 5 essential scripts that are actively used or documented
- Reduced codebase from 9 scripts to 5 focused, maintained tools

**Why This Cleanup:**
- Eliminated confusion from multiple overlapping approaches
- Focused on documented, production-ready methods
- Removed experimental scripts that were superseded by better solutions
- Improved maintainability by reducing code to only what's actively used

**Files Removed:**
- `beeper_keys_api.py` - Alternative API-based approach (documented as future enhancement only)
- `beeper_export_keys_auto.py` - Duplicate auto-export method
- `beeper_keys_incremental_update.py` - Experimental incremental update strategy
- `init_matrix_session.py` - Superseded by `setup_recovery_code.py`

**Files Retained:**
- `setup_recovery_code.py` - **Primary method** for automated server-side key backup (recommended)
- `beeper_decrypt_manual_export.py` - **Fallback method** for manual key export from Web UI
- `extract_beeper_access_token.py` - **Token extraction** from Beeper Desktop database
- `megolm_backup.py` - **Critical library** for Megolm key decryption (third-party GPL)
- `beeper_extract_keys_from_db.py` - **Debugging utility** for extracting keys from local SQLite/IndexedDB

**Current Setup Flow:**
1. **Recommended**: Run `setup_recovery_code.py` for automated server-side backup
2. **Alternative**: Export keys manually from Web UI, then run `beeper_decrypt_manual_export.py`
3. **Both require**: `extract_beeper_access_token.py` for initial token setup

**Impact:**
- No breaking changes - all production code paths remain intact
- Documentation references updated to reflect simplified structure
- Future contributors face less confusion about which approach to use

---

## 2025-12-19: CLI Tool Implementation

**What Changed:**
- Implemented comprehensive CLI tool (`langtalks`) that mirrors all frontend functionality
- Added support for three operational modes: interactive prompts, non-interactive flags, and YAML/JSON config files
- Integrated real-time SSE progress tracking with Rich library (progress bars, spinners, live tables)
- Created output formatters for displaying API results in beautiful, readable terminal format

**Why This Approach:**
- Enables automation and scripting of newsletter generation workflows
- Provides CI/CD integration capabilities without requiring Web UI
- Allows users to save and reuse configurations via YAML/JSON files
- Maintains feature parity with frontend while adding CLI-specific benefits (scripting, automation, config files)

**Architecture:**
```
ui/cli/
├── newsletter_cli.py          # Main Typer app entry point
├── commands/
│   └── generate.py           # Periodic newsletter generation command
├── utils/
│   ├── api_client.py         # HTTP/SSE client for FastAPI backend
│   ├── config_loader.py      # YAML/JSON config loading and merging
│   ├── progress.py           # Rich progress tracker for SSE events
│   ├── validators.py         # Interactive prompts and validation
│   └── formatters.py         # Output formatting (tables, trees, panels)
└── models/
    └── cli_types.py          # CLI-specific enums and constants
```

**Features Implemented:**
1. **Interactive Mode**: Guided prompts for all required fields
2. **Non-Interactive Mode**: All parameters via CLI flags (`--start-date`, `--chats`, etc.)
3. **Config File Support**: Load from YAML/JSON with CLI flag overrides
4. **Real-Time Progress**: SSE streaming with Rich progress bars showing per-chat and overall progress
5. **Output Formatters**: Beautiful terminal display of results including:
   - Per-chat results table with status and output files
   - Consolidation results with statistics and file tree
   - Batch job status tables
   - Run history tables
   - Discussion selection tables (for HITL workflow)
   - Error/success/warning messages with consistent styling

**Files Created:**
- `ui/cli/newsletter_cli.py` - Main CLI entry point
- `ui/cli/commands/generate.py` - Newsletter generation command (500+ lines)
- `ui/cli/utils/api_client.py` - FastAPI HTTP/SSE client
- `ui/cli/utils/config_loader.py` - Configuration file loader with priority merging
- `ui/cli/utils/progress.py` - Rich-based progress tracker
- `ui/cli/utils/validators.py` - Interactive prompt helpers
- `ui/cli/utils/formatters.py` - Output formatting utilities (300+ lines)
- `ui/cli/models/cli_types.py` - Enums for data sources, languages, formats
- `ui/cli/commands/__init__.py`, `ui/cli/utils/__init__.py`, `ui/cli/models/__init__.py` - Package markers

**Files Modified:**
- `pyproject.toml` - Added CLI dependencies (typer, click, rich, sseclient-py) and console script entry point

**Usage Examples:**
```bash
# Interactive mode with guided prompts
langtalks generate periodic

# With config file
langtalks generate periodic --config newsletter.yaml

# Override specific dates with force refresh
langtalks generate periodic --config newsletter.yaml \
  --start-date 2025-01-01 --end-date 2025-01-15 --force-all

# Non-interactive with all flags
langtalks generate periodic \
  --start-date 2025-01-01 \
  --end-date 2025-01-15 \
  --data-source langtalks \
  --chats "LangTalks Community" \
  --language english \
  --format langtalks_format \
  --consolidate \
  --top-k 5

# JSON output for scripting
langtalks generate periodic --config newsletter.yaml --json

# Batch mode for cost optimization
langtalks generate periodic --config newsletter.yaml --batch
```

**Dependencies Added:**
- `typer==0.12.5` - Type-safe CLI framework
- `click==8.1.7` - Pinned for Typer compatibility
- `rich==13.7.0` - Beautiful terminal UI with progress bars and tables
- `sseclient-py==1.8.0` - SSE streaming client for real-time progress

**Console Script:**
```toml
[project.scripts]
langtalks = "ui.cli.newsletter_cli:app"
```

**Future Enhancements** (not yet implemented):
- Run history browsing commands (`langtalks runs list/show`)
- Batch job management commands (`langtalks batch list/status/cancel`)
- HITL workflow commands (`langtalks hitl select/generate`)
- Example config files in `docs/cli/`

---

## 2025-12-13: Newsletter Format Plugin System

**What Changed:**
- Refactored newsletter generation to use a modular plugin architecture
- Each newsletter format (langtalks, mcp_israel) is now a self-contained plugin
- New formats are auto-discovered by scanning `src/custom_types/newsletter_formats/*/`
- Format-specific logic (prompts, schemas, renderers) moved from scattered files to consolidated format directories

**Why This Approach:**
- Adding a new format previously required touching 6+ files across the codebase
- Now adding a format only requires creating a folder with 4 files - no changes to core code
- SOLID-compliant: Open/Closed Principle - extend without modifying existing code
- Single Responsibility: Each format owns its schema, prompts, and rendering

**Architecture:**
```
src/custom_types/newsletter_formats/
├── __init__.py          # Auto-discovery registry
├── base.py              # NewsletterFormatBase ABC
├── langtalks/           # LangTalks format plugin
│   ├── schema.py        # Response schema
│   ├── prompt.py        # System prompt templates
│   ├── renderer.py      # MD/HTML renderers
│   └── format.py        # LangTalksFormat class
└── mcp_israel/          # MCP Israel format plugin
    └── ...              # Same structure
```

**Files Created:**
- `src/custom_types/newsletter_formats/__init__.py` - Format registry with auto-discovery
- `src/custom_types/newsletter_formats/base.py` - NewsletterFormatBase ABC and Protocol
- `src/custom_types/newsletter_formats/langtalks/*` - LangTalks format plugin (4 files)
- `src/custom_types/newsletter_formats/mcp_israel/*` - MCP Israel format plugin (4 files)
- `src/core/generation/generators/newsletter_generator.py` - Generic newsletter generator
- `internal_knowledge/plans/NEWSLETTER_FORMAT_PLUGIN_SYSTEM.md` - Full implementation plan

**Files Modified:**
- `src/core/generation/generators/factory.py` - Simplified to use format registry
- `src/core/generation/generators/__init__.py` - Export new generic generator
- `src/utils/llm/openai_provider.py` - Added `call_with_structured_output_generic()`
- `src/api/newsletters.py` - Use `list_formats()` for validation

**How to Add a New Format:**
```bash
# 1. Create format directory
mkdir -p src/custom_types/newsletter_formats/<format_name>

# 2. Add required files
#    __init__.py, schema.py, prompt.py, renderer.py, format.py

# 3. (Optional) Add examples to data/examples/newsletter_formats/<format_name>/
```

No changes needed to: Constants, Factory, API validation, OpenAI provider

---

## 2025-12-13: OpenAI Batch API Implementation

**What Changed:**
- Implemented OpenAI Batch API support for **50% cost reduction** on translation
- Added async job queue pattern with MongoDB for job persistence
- Batch mode is fully optional - sync mode remains the default
- Background worker processes jobs using OpenAI Batch API
- **Refactored to Strategy Pattern** with provider-agnostic interface for multi-provider support

**Why This Approach:**
- Original plan to batch all LLM calls was architecturally incompatible with LangGraph
- LangGraph workflows have sequential dependencies: `translate` needs `preprocess` output, `generate` needs `rank` output
- Translation stage has the **highest token volume** (50-100+ messages per batch, multiple batches)
- Targeting translation only captures ~80% of cost savings with ~20% of implementation complexity
- Strategy Pattern enables future Anthropic/Gemini batch API support (all offer 50% discount)

**Architecture:**
- User sets `use_batch_api: true` → API returns job_id immediately (HTTP 202)
- Background worker picks up job, processes with Batch API for translation
- Webhook/email notification on completion
- Sync mode (default) unchanged - real-time SSE progress, immediate results

```
src/utils/llm/batch/
├── __init__.py              # Public API exports
├── interface.py             # BatchAPIProvider Protocol
├── types.py                 # BatchRequest, BatchResult, BatchStatus
└── providers/
    ├── __init__.py          # Provider registry (get_provider, list_providers)
    └── openai_provider.py   # OpenAI Batch API implementation
```

**Files Created:**
- `src/utils/llm/batch/` - Generic batch API module with Strategy Pattern
  - `types.py` - Provider-agnostic data types (BatchRequest, BatchResult, BatchStatus)
  - `interface.py` - BatchAPIProvider Protocol definition
  - `providers/openai_provider.py` - OpenAI implementation
- `src/db/batch_jobs.py` - MongoDB job management (BatchJobManager, sync/async APIs)
- `src/workers/batch_worker.py` - Background job processor

**Files Modified:**
- `src/utils/llm/batch_translator.py` - Refactored to use generic BatchAPIProvider
- `src/db/indexes.py` - Added batch_jobs collection indexes (with 30-day TTL)
- `src/custom_types/api_schemas.py` - Added batch API request fields and response models
- `src/api/newsletters.py` - Added batch mode handling and batch job endpoints
- `docker-compose.yml` - Added batch-worker service (profile: batch)

**API Changes:**
- `PeriodicNewsletterRequest` new fields: `use_batch_api`, `batch_webhook_url`, `batch_notification_email`
- New endpoints: `GET /api/batch_jobs/{job_id}`, `GET /api/batch_jobs`, `DELETE /api/batch_jobs/{job_id}`
- Batch mode returns HTTP 202 with `BatchJobQueuedResponse`

**Usage:**
```bash
# Start batch worker (separate process)
docker compose --profile batch up -d

# Submit job with batch mode
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{"use_batch_api": true, "start_date": "2025-01-01", ...}'

# Check job status
curl "http://localhost:8000/api/batch_jobs/{job_id}"
```

**Provider Usage (for developers):**
```python
from utils.llm.batch import get_provider, BatchRequest

provider = get_provider("openai")  # Future: "anthropic", "gemini"
requests = [BatchRequest(custom_id="1", messages=[...])]
result = provider.execute_batch(requests, timeout_minutes=60)
```

**Status:** Implementation complete (Phases 1-3), tests pending

---

## 2025-12-13: Intra-Newsletter Discussion Merging

**What Changed:**
- Added discussion merger module to merge semantically similar discussions from multiple chats into enriched "super discussions"
- New graph node `merge_similar_discussions` runs AFTER `consolidate_discussions` and BEFORE `rank_consolidated_discussions`
- Uses LLM to identify discussions covering the same/overlapping topics across different groups
- Merged discussions combine all messages chronologically with source attribution preserved
- Generates comprehensive title and nutshell capturing ALL perspectives from ALL source groups
- Added `enable_discussion_merging` API parameter (default: true for multi-chat)
- Added `similarity_threshold` API parameter: "strict" | "moderate" | "aggressive" (default: "moderate")

**Why Changed:**
- Prevent repetition within a single newsletter when same topic discussed in multiple groups
- Preserve ALL valuable insights by merging rather than excluding duplicates
- Give ranker accurate picture of combined discussion importance
- Provide readers comprehensive coverage with multi-group attribution
- Ensure each newsletter topic represents ALL perspectives from ALL groups

**Files Created:**
- `src/core/retrieval/mergers/__init__.py` - New module init
- `src/core/retrieval/mergers/discussion_merger.py` - Core merging business logic
- `src/utils/llm/prompts/merging/__init__.py` - Prompts module init
- `src/utils/llm/prompts/merging/merge_discussions.py` - LLM prompts for similarity detection and synthesis

**Files Modified:**
- `src/constants.py` - Added LLM purposes for merging
- `src/utils/llm/openai_provider.py` - Added generic `call_with_json_output` and `call_simple` methods
- `src/graphs/multi_chat_consolidator/state.py` - Added discussion merging state fields
- `src/graphs/multi_chat_consolidator/consolidation_nodes.py` - Added `merge_similar_discussions` node
- `src/graphs/multi_chat_consolidator/graph.py` - Added node to graph, updated edges
- `src/custom_types/api_schemas.py` - Added API parameters
- `src/api/newsletters.py` - Wired parameters to orchestrator state

**Usage:**
```json
{
  "start_date": "2025-12-01",
  "end_date": "2025-12-15",
  "data_source_name": "langtalks",
  "whatsapp_chat_names_to_include": ["LangTalks Community", "LangTalks - Code Generation Agents"],
  "summary_format": "langtalks_format",
  "enable_discussion_merging": true,
  "similarity_threshold": "moderate"
}
```

**Merged Discussion Output:**
```json
{
  "id": "merged_discussion_1",
  "is_merged": true,
  "title": "RAG Implementation: Chunking Strategies and Best Practices",
  "source_discussions": [
    {"id": "disc_3", "group": "LangTalks Community", "original_title": "RAG chunking strategies"},
    {"id": "disc_12", "group": "Code Generation Agents", "original_title": "Best practices for RAG"}
  ],
  "messages": [...],
  "nutshell": "Comprehensive discussion on RAG implementation from multiple community perspectives...",
  "num_messages": 34,
  "num_unique_participants": 12
}
```

**Graph Flow:**
```
consolidate_discussions → merge_similar_discussions → rank_consolidated_discussions → ...
```

---

## 2025-12-12: Anti-Repetition System

**What Changed:**
- Added newsletter history loader module to load and parse previous newsletters
- Extended ranking prompt with repetition analysis using LLM semantic matching
- Added new fields to ranking output: `repetition_score` ("high"/"medium"/"low"/null) and `repetition_identification_reasoning`
- Discussions that match previous PRIMARY discussions get high repetition score (-3 to -4 importance penalty)
- Discussions that match previous SECONDARY discussions get medium repetition score (-2 penalty)
- Discussions that match previous WORTH_MENTIONING get low repetition score (-1 penalty)
- High-repetition items are filtered out from the `worth_mentioning` section
- Added `previous_newsletters_to_consider` API parameter (default: 5, 0 disables)

**Why Changed:**
- Prevent newsletters from repeating topics already covered in previous editions
- Improve subscriber experience by prioritizing fresh, novel content
- The "Worth Mentioning" section should avoid repeating already-covered topics
- Cross-edition deduplication ensures diverse newsletter content over time

**Files Created:**
- `src/core/retrieval/history/__init__.py` - New module init
- `src/core/retrieval/history/newsletter_history_loader.py` - Load and parse previous newsletters

**Files Modified:**
- `src/utils/llm/prompts/ranking/rank_discussions.py` - Added REPETITION_ANALYSIS_SECTION, NO_PREVIOUS_NEWSLETTERS_SECTION
- `src/core/retrieval/rankers/discussion_ranker.py` - Accept previous_newsletter_context, pass to LLM, include repetition in brief_mention_items
- `src/graphs/subgraphs/state.py` - Added anti-repetition fields to DiscussionRankerState
- `src/graphs/multi_chat_consolidator/state.py` - Added previous_newsletters_to_consider to ParallelOrchestratorState
- `src/custom_types/api_schemas.py` - Added previous_newsletters_to_consider API parameter
- `src/graphs/subgraphs/discussions_ranker.py` - Load previous newsletter context before ranking
- `src/graphs/multi_chat_consolidator/consolidation_nodes.py` - Pass anti-repetition config to ranker
- `src/core/generation/generators/langtalks.py` - Filter high-repetition brief mentions
- `src/core/generation/generators/mcp.py` - Filter high-repetition brief mentions

**Usage:**
```json
{
  "start_date": "2025-12-01",
  "end_date": "2025-12-15",
  "data_source_name": "langtalks",
  "whatsapp_chat_names_to_include": ["LangTalks Community"],
  "summary_format": "langtalks_format",
  "previous_newsletters_to_consider": 5  // NEW: default is 5, 0 disables anti-repetition
}
```

**Ranking Output Fields (new):**
```json
{
  "ranked_discussions": [
    {
      "discussion_id": "...",
      "rank": 1,
      "importance_score": 8,
      "repetition_score": "medium",
      "repetition_identification_reasoning": "This discussion about 'RAG for Books' is similar to the secondary discussion 'RAG Implementation Strategies' from the 2025-10-01_to_2025-10-14 newsletter."
    }
  ]
}
```

---

## 2025-12-06: Fail-Fast Error Handling Improvements

**What Changed:**
- Replaced all bare `except:` blocks with `except Exception as e:` and proper logging
- Progress queue failures are now logged with warning level (non-critical but visible)
- Discussion count and file size calculation failures are now logged
- Metadata addition failure in consolidated newsletter is now a hard error (was silently swallowed)
- MCP content generator now requires `featured_discussions` parameter (consistent with LangTalks)

**Why Changed:**
- Silent failures make debugging difficult and hide potential issues
- Fail-fast approach ensures problems are surfaced immediately
- Consistent error handling across all content generators (DRY principle)
- All formats (LangTalks, MCP, and future formats) now follow the same pattern

**Files Modified:**
- `src/services/workflows/newsletter_generation.py` - Fixed 7 bare except blocks for progress queue, 1 for discussion count, 1 for file size
- `src/services/workflows/cross_chat_consolidation_nodes.py` - Made metadata addition a hard error
- `src/services/chat_summary_generators/.../content_generator_community_mcp.py` - Require `featured_discussions`
- `src/services/shared/llm_callers/openai/openai_caller.py` - MCP prompt uses `brief_mention_items`

---

## 2025-12-06: Worth Mentioning Enhancement

**What Changed:**
- Connected the discussion ranker output to the content generator, so the `worth_mentioning` section now uses pre-ranked discussions
- Added `top_k_discussions` parameter (default: 5) to control how many discussions are featured in full
- Discussions beyond top-K are now automatically categorized as `brief_mention` and used for the "נושאים נוספים שעלו" section
- The ranker now generates a `one_liner_summary` for each discussion - a teachable moment capturing the key practical insight
- Updated LLM prompt to emphasize teachable moments, practical tips for AI engineers
- Applied to both single-chat and cross-chat consolidation flows

**Why Changed:**
- Previously, the ranker output was computed but NOT used by the content generator
- The `worth_mentioning` section was generated from scratch by the LLM without leveraging the ranked discussions
- Now, discussions that don't make the top-K cut become candidates for brief one-liner mentions
- This ensures no valuable discussions are lost and provides more teachable, actionable content

**Files Modified:**
- `src/api/models.py` - Added `top_k_discussions` field
- `src/services/workflows/states.py` - Added `top_k_discussions` to state schemas
- `src/services/workflows/discussions_ranker.py` - Added one-liner generation, top-k categorization
- `src/services/workflows/newsletter_generation.py` - Use ranking to filter discussions
- `src/services/workflows/cross_chat_consolidation_nodes.py` - Same changes for consolidated flow
- `src/services/chat_summary_generators/.../content_generator_community_langtalks.py` - Accept pre-filtered discussions
- `src/services/shared/llm_callers/openai/openai_caller.py` - Updated prompt for worth_mentioning
- `src/api/routes/newsletters.py` - Pass `top_k_discussions` to orchestrator

**Error Handling (Fail-Fast):**
- If ranking file is missing → `RuntimeError` with descriptive message
- If ranking file has invalid JSON → `RuntimeError` with parse error details
- If `featured_discussion_ids` field is missing → `RuntimeError` suggesting to re-run with `force_refresh_discussions_ranking=true`
- If no discussions match the featured IDs → `RuntimeError` showing the ID mismatch
- No silent fallbacks - all issues are surfaced immediately

**Usage:**
```json
{
  "start_date": "2025-10-01",
  "end_date": "2025-10-14",
  "data_source_name": "langtalks",
  "whatsapp_chat_names_to_include": ["LangTalks Community"],
  "summary_format": "langtalks_format",
  "top_k_discussions": 5  // NEW: default is 5, can be 1-20
}
```

---
