# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.15.0] - 2026-06-05

### Added
- Admin-facing **Extracted Images** gallery infrastructure. A new admin-only API surface serves and lists images that the vision pipeline extracted from community chats. `GET /api/media/images/{image_id}` streams the raw bytes through the `MediaStorageInterface` (new `read()` method on the interface and `LocalMediaStorage`, with a path-traversal guard and S3-ready factory `get_media_storage()`), returning the stored mimetype and an immutable `Cache-Control`. `GET /api/images` returns a paginated, discussion-enriched feed filterable by any combination of community (`data_source_name`), `chat_name`, `discussion_id`, and `start_date`/`end_date` (new `ImagesRepository.get_image_by_id`, `query_images`, `count_images`); each item carries a ready-to-use `image_url` and its associated discussion title. Both routers self-guard with `require_admin`. Frontend: a new admin-only "Extracted Images" tab (`ExtractedImagesGallery`) renders a filterable, paginated card grid with per-image metadata (source group, timestamp, sender, description) and a per-card accordion linking the image to its discussion. Backend-only behavior is unchanged when the vision pipeline is disabled (the gallery simply shows no images).
- MongoDB connection-pool observability. A `pymongo.monitoring` listener (`src/observability/metrics/mongo_pool_listener.py`) attached to both the async `AsyncIOMotorClient` and the sync `MongoClient` at construction now feeds three Prometheus series at `/metrics`: `mongodb_pool_connections{client,state}` (created / checked_out / available), `mongodb_pool_checkout_wait_seconds{client}` (histogram of time waited to acquire a connection), and `mongodb_pool_checkout_failures_total{client,reason}` (the saturation alarm: non-zero means checkouts timed out or errored). The `client` label distinguishes the async pool (API/graphs/RAG/agent) from the sync pool (LangGraph checkpointer). Purely additive and fail-soft; recording errors never affect DB operations. Makes the single shared pool measurable so connection-pool exhaustion can be confirmed with data before any decision to split clients per workload.
- Individual user accounts for the web UI, replacing the single shared-password gate. Each account has an email + argon2id-hashed password and an `admin` or `viewer` role. Login (`POST /api/auth/login`) now takes `{email, password}` and issues a per-user Fernet session cookie carrying the user id, role, and a `session_epoch`; `require_session` re-loads the user on every request and rejects disabled accounts or stale epochs, so disabling a user or resetting their password revokes their live sessions immediately. New admin-only router (`/api/auth/users`): create/invite, list (never exposes `password_hash`), admin password reset (bumps epoch), disable/enable, and delete, all gated by a `require_admin` dependency; admins cannot disable or delete their own account. There is no open self-signup. A bootstrap admin is seeded on first start from `LANGRAG_BOOTSTRAP_ADMIN_EMAIL` / `LANGRAG_BOOTSTRAP_ADMIN_PASSWORD` only when the users collection is empty. Frontend: the login card now collects email + password, the header shows the signed-in user and role, and an admin-only "Users" tab manages accounts. New deps: `argon2-cffi`, `email-validator`.
- `scripts/migrate_periodic_output_layout.py`: one-time migration that moves existing flat run directories into per-community subdirectories. Dry-run by default; `--apply` performs the moves and refuses to overwrite an existing destination. Tolerates legacy `_merged`-suffixed run dirs.

### Changed
- Split RAG conversation message history out of the embedded `rag_conversations.messages` array into a dedicated `rag_messages` collection (one document per turn, referenced by `session_id`), removing the only real 16MB BSON document-size risk in the codebase: a long-lived chat session now grows in message *count* (cheap, O(1) inserts, indexed history reads) rather than in document *size* (a hard mid-conversation write failure). The session document keeps metadata only. Cross-collection integrity is explicit — a unique `message_id` index, owner-scoped access unchanged, a cascade `delete_many` on session delete, and multi-document transactions wrapping both append (insert + `updated_at` bump) and delete (session + messages). New `RAGMessagesRepository`; `ConversationsRepository` delegates to it while keeping every public signature, so `ConversationManager` and the HTTP/SSE endpoints are behavior-identical (the `GET /api/rag/sessions/{id}` response still carries full history, now hydrated on demand). The first-message auto-title check counts `rag_messages` instead of measuring an array. New index block `rag_messages(message_id unique; session_id+created_at desc)`. One-time backfill: `scripts/migrate_rag_conversations_messages.py` (dry-run/apply, idempotent, per-session transaction). Validated by `tests/integration/rag/test_conversations_messages_split.py` (SC1–SC8 incl. transaction rollback and a 16MB regression guard, plus migration backfill/idempotency).
- Email addresses are canonicalized (lowercased + trimmed) at the users-repository boundary so casing cannot fork an identity or bypass a disable.
- The async batch-orchestration router is now session-gated like the other UI-data routers (it was previously reachable unauthenticated).
- Corrected the stale Cloudflare SSL-mode note in `terraform/main.tf`: it claimed "Full" but the live zone is "Flexible" (the origin serves only HTTP on :80; Full would 521 against it). The setting remains unmanaged by Terraform (the DNS-scoped API token lacks zone-settings permission).
- Periodic-newsletter output is now nested per community: runs are written to `output/generate_periodic_newsletter/<community>/<community>_<start>_to_<end>/` instead of a flat list of run directories. The top level now contains one subdirectory per community rather than every run intermixed. The `run_id` (the run directory's leaf name) is unchanged, so the runs browser, delete, and newsletter-content endpoints keep working. New path helpers in `src/utils/output_paths.py` (`build_run_output_dir`, `resolve_run_dir`, `parse_run_id`, `community_of_run_id`) are the single source of truth for the layout.
- Deduplicated the four purpose-specific prompt-input builders that were byte-for-byte identical across the OpenAI, Anthropic, and Gemini providers into a shared `PromptInputBuilderMixin` (`src/utils/llm/prompt_inputs.py`); each provider now inherits the mixin and binds it from its `INPUT_PURPOSE_MAP`. Behavior-preserving: the prompts, model, and temperature produced are unchanged, and only the provider-specific API-call shape stays per module.

### Security
- Closed a cross-tenant IDOR on the RAG session API. `GET`/`DELETE /api/rag/sessions/{id}` and `GET /api/rag/sessions` were gated only by a valid API key with no ownership check, so any key could read another tenant's full conversation history, enumerate their sessions, or destructively delete them. Sessions are now stamped with the creating key's `owner` and every read/list/delete is owner-scoped (`ConversationsRepository`, `ConversationManager`, and the `rag_conversation` endpoints, which now inject the key record and pass `owner`); a mismatch returns 404. The streaming and non-streaming chat endpoints scope session access the same way. New compound index `(owner, updated_at desc)` backs the owner-scoped listing. Legacy ownerless sessions become inaccessible via the API (safe-fail direction) rather than leaking.
- Restored real path-traversal containment on the file-serving and run-deletion endpoints. The newsletter file/HTML viewers (`src/api/newsletter_gen.py`) and run delete/newsletter endpoints (`src/api/observability/runs.py`) imported `resolve_path_within_base`/`PathContainmentError` that did not exist anywhere — the references were live (call sites + `except` clauses) but the implementation was never landed, so the module raised `ImportError` and the symbols provided no protection. Implemented `resolve_path_within_base` (`src/utils/validation.py`) using realpath + `os.path.commonpath` (resolves symlinks and `..`, rejects sibling-prefix bypasses like `<base>-evil` that a `startswith` check would allow) and added `PathContainmentError` (`src/custom_types/exceptions.py`). Covered by `tests/unit/test_path_containment.py`.

### Fixed
- The `mcp-server` service now has its own Docker healthcheck. It reuses the app `Dockerfile` (whose `HEALTHCHECK` probes `:8000/health`) but listens on `:8765` and serves no plain `/health` route, so Docker always marked the container `unhealthy` even though the MCP process was running. Overridden with a stdlib TCP-connect probe to `:8765`.
- `docker-compose.yml` now forwards `LANGRAG_BOOTSTRAP_ADMIN_EMAIL` and `LANGRAG_BOOTSTRAP_ADMIN_PASSWORD` into the `app` container. The user-accounts feature requires these when the `users` collection is empty, but the `app` service passes env through explicitly (no `env_file`) and these two were never wired, so a clean production deploy crash-looped on the bootstrap-admin fail-fast despite the values being present in `.env`.
- Fixed two committed `ImportError`s that prevented the FastAPI app from starting at all. `src/api/newsletter_gen.py`/`src/api/observability/runs.py` imported the never-defined `resolve_path_within_base` and `PathContainmentError` (now implemented — see Security), and `src/api/observability/runs.py` imported `DiagnosticReportStatus` and `NEWSLETTER_OUTPUT_EXTENSIONS` from `constants`, neither of which existed. Both routers are mounted in `main.py` at import time, so the whole app failed to boot. Added the `DiagnosticReportStatus` `StrEnum` (clean / issues_found / unknown) and the `NEWSLETTER_OUTPUT_EXTENSIONS` constant to `src/constants.py`. The app now imports and compiles all graphs cleanly.
- Agent memory is no longer skipped on long conversations. `route_after_agent` sent long no-tool-call turns to `summarize`, whose edge looped back to `agent` (`summarize → agent`); the agent could re-route to `summarize` and terminate without ever reaching `extract_memory`, so the highest-context sessions never persisted memory. Summarization is end-of-turn context compaction (the final answer is already produced), so the edge is now `summarize → extract_memory → END`.
- Moved blocking synchronous JSON file I/O off the event loop in the per-chat newsletter graph (`src/graphs/single_chat_analyzer/graph.py`, all six node read sites) and the link-enricher async nodes (`src/graphs/subgraphs/link_enricher.py`). Bare `open()` + `json.load`/`json.dump` inside `async def` nodes stalled every concurrent chat worker on the shared loop under the parallel orchestrator. Reads/writes now go through a new shared `src/utils/async_json_io.py` (`load_json_async`/`dump_json_async`, backed by `asyncio.to_thread`) or wrap the existing sync helpers in `asyncio.to_thread`.
- Made the MongoDB cache layer observable instead of silently swallowing failures at DEBUG. Initialization and per-operation failures in `src/db/cache.py` now log at WARNING with structured context and distinguish "cache unavailable" from a genuine miss; the cache remains fail-soft (optional) but a real outage is now visible in production logs. Also replaced a silent `except Exception: pass` on the OpenAI provider's Langfuse error-observation update with a debug log.
- Added counts to two previously-silent data drops in WhatsApp preprocessing (`src/core/ingestion/preprocessors/whatsapp.py`): the number of poll-response events filtered from the message stream, and the number of messages (and unique thread references) whose out-of-window reply references were replaced with a placeholder. Improves run diagnosability; no behavior change.
- Hardened the discussion-separation and message-translation prompts against prompt injection from attacker-controlled WhatsApp message bodies. Untrusted message content serialized into the user prompt is now fenced in an `<untrusted_chat_data>` block with an explicit instruction that its contents are data to analyze, never instructions to follow (`src/utils/llm/prompt_inputs.py`).
- Fixed asymmetric sampling in the discussion ranker that dropped a single-message discussion's content from the "last message" sample slot. `_first_last_sample` now returns `[content]` for one message and `[first, last]` for many (`src/core/retrieval/rankers/discussion_ranker.py`). Covered by `tests/unit/test_discussion_sample_messages.py`.
- Converted the agent graph's `NodeNames` to a `StrEnum` (`src/agent/graph.py`) so a typo'd node identifier is an `AttributeError` at the call site rather than a silently-misrouted string, matching the convention used by the other graphs.
- Restored www.langrag.ai from an infinite HTTP→HTTPS redirect loop (ERR_TOO_MANY_REDIRECTS). The origin `nginx.conf` unconditionally 301'd port-80 traffic to HTTPS via `if ($host != "localhost")`, but Cloudflare runs in Flexible SSL mode and re-fetches the origin over plain HTTP, so every proxied request bounced back to HTTPS forever. The redirect is now gated on `if ($http_x_forwarded_proto = "http")`, so the origin redirects only genuinely-insecure clients and never Cloudflare's already-HTTPS traffic; localhost dev (no forwarded header) is unaffected.

## [1.14.0] - 2026-05-31

### Added
- Agent golden conversation eval gate (v1.14.0 release gate): `tests/evals/agent/golden_conversations.jsonl` ships 6 scenarios — new-user newsletter flow, returning-user "run it again" memory reuse, cross-community ACL denial, RAG query inside an agent turn, tool-call ceiling halts a runaway loop, and memory-extractor persistence of a high-importance fact. `scripts/run_agent_evals.py` drives the runtime with scripted LangChain LLMs (no Anthropic credits), exits 0 only when pass-rate ≥ threshold (default 1.0). `.github/workflows/agent-evals.yml` runs unit + integration + the eval gate on PRs touching `src/agent/**`, `src/api/agent_chat.py`, the test trees, or the workflow file itself. `tests/integration/agent/test_evals_runner.py` invokes the runner as a subprocess and asserts exit 0 — proves the eval-gate harness is itself healthy.

### Added
- Agent Prometheus metrics module (`src/observability/metrics/agent_metrics.py`): `agent_tool_calls_total{tool, status}` incremented per tool invocation (success vs error); `agent_session_duration_seconds` histogram via `track_session_duration()` context manager; `agent_memory_writes_total{namespace}` incremented inside the memory extractor on every persisted memory; `agent_budget_halts_total{reason}` incremented by `route_after_budget` when the per-turn tool-call ceiling is hit; `agent_acl_denials_total{tool, community}` incremented by the tool node on `CommunityPermissionError`. Lazy singleton with `reset_for_tests()` so the process-global Prometheus registry doesn't refuse re-instantiation under pytest. The agent graph's `tools_node` is the central wiring point: success path records `tool_calls_total{status=success}`; ACL denial records both `tool_calls_total{status=error}` AND `acl_denials_total`; ValueError + generic exception paths each record `tool_calls_total{status=error}`. Test: `tests/unit/observability/test_agent_metrics.py` (6 tests covering each counter's increments, label sets matching plan §I, and the histogram observation).

### Added
- HITL (Human-in-the-Loop) gating on destructive agent tools: `delete_schedule`, `forget`, and `generate_newsletter(send_email=True)` now call LangGraph `interrupt(...)` BEFORE any side effect. The agent graph's tools node propagates `GraphInterrupt` instead of swallowing it, so the graph suspends at the checkpoint; the route handler emits an `interrupt_required` SSE event; the frontend pops `InterruptDialog` and on user click POSTs `/api/agent/chat/resume` with `Command(resume="approve" | "reject")`. Reject returns `{deleted: false, reason: "rejected_by_user"}` (or the equivalent for the other tools) without firing the side effect. Tests: `tests/integration/agent/test_hitl_destructive_tools.py` (3 end-to-end tests against the real LangGraph runtime — approve fires the kickoff, reject does NOT fire it, send_email=False skips the interrupt entirely). The pre-existing `tests/unit/agent/tools/test_*.py` happy-path tests for the destructive variants now assert that bare `.ainvoke()` outside a graph context fails AND that the side effect never fires.

- Agent chat frontend (v1.14.0 scope): `ui/frontend/src/components/agent/AgentChat.tsx` is a split-pane container (message thread + composer on the left, `ArtifactPanelRouter` on the right) wired to the new SSE streaming endpoint via `ui/frontend/src/hooks/useAgentStream.ts`. The hook reducer encodes the `AgentEventType` taxonomy and is parser-isolated so synthetic SSE chunks can drive it under test. Companion components: `ToolCallChip` (inline tool-invocation pill), `InterruptDialog` (HITL approve/reject modal — wired but inactive until commit 10), `MemoryInspector` (list/forget user memories with optimistic delete + rollback on failure). New TS types in `ui/frontend/src/types/agent.ts` mirror the backend `AgentEventType` enum and DTOs. `agentApi` helpers added to `ui/frontend/src/services/api.ts`. Tests: `useAgentStream.test.ts` (12 reducer + parser invariants — token accumulation, tool-call round-trip by call_id, error → status='error', artifact_panel accumulation, interrupt_required payload preservation, error event flips streaming off, done event flips done, unknown events ignored, malformed data no-crash, multi-line data parse, reset clears state) + `MemoryInspector.test.tsx` (2 tests: list+render, optimistic delete + rollback on API failure). 14 new frontend tests, all passing.

## [1.13.0] - 2026-05-31

### Added
- `knowledge/plans/AGENTIC_CHATBOT_LAYER.md`: full design + TDD plan for the upcoming agentic chatbot layer (admin-scoped LangGraph `StateGraph` with tool registry, `MongoDBStore`-backed long-term memory, ACL-gated tool execution, HITL interrupts, chat-token quotas, SSE streaming UI). Targets v1.13.0 (foundation + agent runtime + streaming) and v1.14.0 (frontend + hardening + evals).
- Agentic chatbot data model foundation: `users`, `user_api_keys`, `agent_sessions`, `agent_memories` MongoDB collections with Pydantic schemas (`UserDocument`, `UserApiKeyDocument`, `AgentSessionDocument`, `AgentMemoryDocument`), `UserRole` and `MemoryNamespace` `StrEnum`s, four matching async repositories under `src/db/repositories/`, compound + TTL + unique indexes registered in `src/db/indexes.py`, and idempotent Atlas Search index creation for `agent_memory_embeddings` (vector) and `agent_memory_lexical` (lexical) so the v1.13.0 `$rankFusion` retriever has both legs available. No user-visible behavior yet; agent runtime and routers land in later commits.
- Repository tests `tests/unit/db/test_{users,user_api_keys,agent_sessions,agent_memories}_repository.py` covering CRUD round-trips, unique-email constraint, episodic-TTL set-only-on-episodic, cross-`user_id` isolation on delete, and `touch_*` best-effort updates.
- Integration test `tests/integration/db/test_agent_indexes_created.py` asserts the four new collections' indexes are registered after `ensure_indexes()` and (when mongot is reachable) that both agent-memory search indexes exist.
- Test helper `tests/_helpers/mongo.py::requires_mongodb` for shared skip-when-MongoDB-down behavior across unit + integration suites.

### Changed
- Extracted the shared `$rankFusion` aggregation builder to `src/db/queries/rankfusion.py::build_rankfusion_pipeline` + `normalize_rrf_scores`, and migrated `src/rag/retrieval/hybrid_search.py::hybrid_search_chunks` to use it. Behavior-preserving refactor: the v1.13.0 agent memory retriever will reuse the same helper instead of duplicating the fusion stage. RAG eval gate parity verified at top-K (`retrieval_recall_at_5` 0.369 vs 0.369 baseline, judge-driven metrics within normal LLM jitter — both failing metrics pre-date this refactor). Backwards-compat shim `_normalize_rrf_scores` kept in `hybrid_search.py` so existing tests don't break. New tests: `tests/unit/db/test_rankfusion_builder.py` (pipeline shape + normalization corner cases) and `tests/unit/db/test_rankfusion_rag_parity.py` (snapshot diff against pre-refactor pipeline).
- Long-term memory subsystem for the agent runtime: `src/agent/memory/mongodb_store.py::MongoDBStore` implements LangGraph's async `BaseStore` over `agent_memories` (namespace `(user_id, semantic|episodic|procedural)`, multi-tenancy enforced at the aggregation layer — every `aget`/`asearch`/`adelete` pre-filters on `user_id`); `src/agent/memory/hybrid_memory_search.py` performs `$rankFusion` retrieval through the shared builder; `src/agent/memory/extractor.py` parses an LLM-emitted JSON array of memory candidates and persists items above the importance threshold (episodic memories auto-TTL to 30 days, semantic + procedural persist); `src/agent/memory/retriever.py` hybrid-searches all three namespaces per turn and returns top-K deduped; `src/agent/memory/summarizer.py` compresses old turns once `len(messages)` exceeds the threshold via `RemoveMessage`. All four components are LLM-injectable for the v1.13.0 agent graph (commit 7). Tests under `tests/unit/agent/memory/` cover round-trip, cross-tenant isolation, BSON-vector storage, TTL semantics, namespace dispatch, dedupe, threshold gating, fenced-JSON tolerance, and recent-message preservation (36 new tests).
- Agent auth + ACL + user-context propagation (`src/agent/auth/`): `UserContext` dataclass + `ContextVar`-backed `current_user_context()` so tools read the active principal without it ever appearing in tool JSON schemas (the LLM cannot forge it); `assert_user_owns_community` + `CommunityPermissionError` enforce per-community ACL with `ValueError` on unknown community keys (no silent typos); `filter_communities` strips unauthorized + unknown entries from multi-community requests; `resolve_user_from_api_key` looks up `user_api_keys` → `users` and assembles the `UserContext` with per-UTC-day quota remainders; `require_user` is the FastAPI dependency parallel to `require_api_key` for the public RAG path. Tests under `tests/unit/agent/auth/` + `tests/unit/agent/runtime/` cover ACL happy-path + denial + unknown-community handling, filter_communities ordering + unknown-key drop, valid-key resolution, missing/unknown/disabled/dangling-key 401 paths, and the `ContextVar` invariants — including concurrent `asyncio.gather` isolation across tenants (19 new tests).
- Agent tool registry (`src/agent/tools/`): 15 tools across 5 domains — RAG (`rag_query`, `rag_search`, `list_rag_sources`, thin wraps over the existing `src/rag/mcp/tools.py`), community (`list_my_communities`, `describe_community`), memory (`remember`, `forget`, `list_memories`), newsletter (`generate_newsletter` via injected `kickoff_fn`, `get_run_status`, `list_recent_runs`, `get_newsletter`), and schedule (`create_schedule`, `list_schedules`, `delete_schedule`). All community-targeting tools gate on `assert_user_owns_community` before any side effect; reads silently drop cross-tenant rows from listings (no enumeration leak); destructive `delete_schedule` returns the same `not_found` shape for unknown and cross-tenant ids. Headline safety invariant proven by `tests/unit/agent/tools/test_tool_schemas.py`: NO tool exposes `user_context` or `user_id` in its JSON schema — the principal is injected via the contextvar, never accepted from the LLM. 25 new tests.
- Agent runtime + non-streaming `/agent/chat` endpoint: `src/agent/state.py::AgentState` TypedDict, `AgentStateKeys` added to `src/graphs/state_keys.py`, `src/agent/graph.py::build_agent_graph` compiles the LangGraph `StateGraph` (load_memory → agent → tools → check_budget → … → extract_memory → END) with ACL-aware tool dispatch (catches `CommunityPermissionError` + `ValueError` and surfaces them as `ToolMessage(status="error")` so the LLM sees denials in its loop), and `src/agent/runtime.py` is the process-wide lazy builder that wires the production Anthropic LLMs, `MongoDBStore`, `MongoDBSaver` checkpointer, and a real newsletter-orchestrator kickoff. New API surface mounted only when `AGENT_ENABLED=true`: `POST /api/agent/sessions`, `POST /api/agent/chat`, `GET /api/agent/sessions`, `DELETE /api/agent/sessions/{id}`, `GET /api/agent/memories`, `DELETE /api/agent/memories/{id}`. New `AgentSettings` config block (`AGENT_*` env prefix) with `enabled`, `agent_model`, `memory_model`, `max_tool_calls_per_turn`, `summarize_threshold`, `summarize_keep_recent`, `importance_threshold`, `memory_top_k`. Per plan §D, configurable propagation reads from `langgraph.config.get_config()` (closures + the function-signature inspector don't see config injection cleanly otherwise). Tests: `tests/unit/agent/test_graph_routing.py` (5 tests covering happy path, tool-call round trip, ACL denial → error ToolMessage, unknown-community ValueError → error ToolMessage, tool-call ceiling enforcement) and `tests/integration/agent/test_chat_non_streaming.py` (3 tests covering 401 without API key, end-to-end session-create + chat returning the assistant reply, and AGENT_ENABLED=false producing 404).
- SSE streaming + resume for the agent: `POST /api/agent/chat/stream` returns the documented `AgentEventType` taxonomy — `tool_call_started`, `tool_call_finished`, `token`, `artifact_panel`, `interrupt_required`, `memory_written`, `budget_warning`, `error`, `done` — driven by `graph.astream(stream_mode="updates")`. `POST /api/agent/chat/resume` accepts `{session_id, decision}` and resumes a HITL-interrupted turn via `Command(resume=...)`. Tool-call args are redacted (string fields >200 chars truncated) before SSE emission to keep the chip-render bundle small. `AgentEventType` `StrEnum` added to `src/constants.py` alongside `RAGEventType`. Tests: `tests/integration/agent/test_chat_streaming.py` (4 tests covering the full event order for a scripted tool-call turn, session-not-found error path, 401 without API key, and the resume endpoint contract).

## [1.12.0] - 2026-05-26

### Added
- Runtime LLM-judge scoring for RAG responses (`src/rag/evaluation/runtime/`): a thin `langchain-openai` wrapper around three prompt templates (faithfulness, answer relevancy, hallucination) that scores each response and dual-writes scores to MongoDB (`rag_evaluations`) and Langfuse (trace scores). Background-fire-and-forget, fail-soft (one judge or sink failure never blocks the conversation).
- `RuntimeEvalSettings` config block (`RUNTIME_EVAL_*` env prefix) with `enabled`, `metrics`, `sampling_rate`, per-metric thresholds (`faithfulness_threshold`, `answer_relevancy_threshold`, `hallucination_threshold`), `eval_model` (default `gpt-4.1-mini`), and `judge_timeout_seconds`.
- `LANGFUSE_TRACE_ID` field in `RAGConversationStateKeys` so judge scores attach to the originating Langfuse trace.

### Changed
- `RAGConversation.evaluate_node` rewired from `get_settings().deepeval` + DeepEval at runtime to `get_settings().runtime_eval` + the new in-process scorer. DeepEval is still used by the CI eval gate, but is intentionally NOT imported anywhere under `src/rag/evaluation/runtime/`; the boundary is guardrailed by `tests/unit/rag/runtime/test_no_deepeval_import.py`.

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

[Unreleased]: https://github.com/eladlaor/langrag/compare/v1.15.0...HEAD
[1.15.0]: https://github.com/eladlaor/langrag/compare/v1.14.0...v1.15.0
[1.14.0]: https://github.com/eladlaor/langrag/compare/v1.13.0...v1.14.0
[1.13.0]: https://github.com/eladlaor/langrag/compare/v1.12.0...v1.13.0
[1.12.0]: https://github.com/eladlaor/langrag/compare/v1.11.0...v1.12.0
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
