# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LangRAG: automated newsletter generation from WhatsApp group chat messages via Beeper. Extracts, decrypts, processes, translates, and summarizes discussions into structured newsletters using LangGraph workflows and OpenAI.

**Tech Stack**: FastAPI 0.115.0 + LangGraph 1.0+ (native async) + OpenAI (langchain-openai) + MongoDB (Motor async) + matrix-nio (Beeper decryption) + React 19 frontend + Docker/nginx

## Build, Run, Test Commands

### Running the Application (Docker Required)

```bash
docker compose up -d                    # Start all services
docker compose logs -f                  # View logs
docker compose down                     # Stop all services
```

**Access**: http://localhost (Web UI), http://localhost/docs (API docs)

**Rebuild after code changes**:
```bash
docker compose down && docker compose build --no-cache && docker compose up -d
```

**Frontend rebuild** (when only frontend changed):
```bash
rm -rf ui/frontend/build && docker compose build --no-cache && docker compose up -d
```

### Testing

```bash
pytest tests/test_e2e_pipeline.py -v                                          # E2E pipeline tests
pytest tests/test_e2e_pipeline.py::test_periodic_newsletter_generation -v     # Single test
pytest tests/unit/ -v                                                         # Unit tests
pytest tests/unit/test_discussion_ranker.py -v                               # Single unit test file
pytest tests/unit/rag/ -v                                                     # RAG unit tests (chunker, source, evaluator, metrics)
pytest tests/integration/rag/ -v                                              # RAG integration tests (Docker required, auto-skip otherwise)
```

Pytest config is in `pyproject.toml`: `pythonpath = ["src", "."]`, `asyncio_mode = "auto"`. Tests require Docker running.

### Linting & Formatting

```bash
ruff check . --fix    # Lint with auto-fix
ruff format .         # Format
```

Ruff config: `line-length = 500`, selects `E, F, W, UP` rules (in `pyproject.toml`).

### Frontend Development

```bash
cd ui/frontend
npm install           # Install dependencies
npm run build         # Production build
npm run start         # Dev server (port 3000)
```

### Package Management

Use `uv` (not pip) for Python dependencies. Dependencies defined in `pyproject.toml`, locked in `uv.lock`.

## Architecture

### Pipeline Flow (Periodic Newsletter)

```
FastAPI → ParallelOrchestratorGraph
  ├─> dispatch_chats (parallel)
  ├─> chat_worker [parallel] → NewsletterGenerationGraph (11 nodes)
  │    └─> extract → slm_prefilter → extract_images → preprocess → translate → separate → rank → associate_images → generate → enrich → translate_final
  ├─> aggregate_results
  └─> Conditional: consolidate_chats?
       ├─> TRUE: consolidate → rank (cross-chat) → generate → enrich → translate
       └─> FALSE: output_handler
```

### Daily Summaries (Cross-Day)

```
FastAPI → DataPreparationGraph + ContentGenerationGraph
  ├─> Phase 1: Extract + Aggregate + Rank (across ALL days)
  └─> Phase 2: Generate Newsletter
```

### LangGraph Patterns

- **Node Signature**: `async def node(state: State, config: RunnableConfig | None = None) -> dict`
- **Graph Invocation**: `result = await graph.ainvoke(state, config)`
- **MongoDB Access**: `tracker = _get_tracker(); await tracker.create_run(...)`
- **Subgraph Calls**: `await subgraph.ainvoke(substate, config=config)`
- **State Schemas**: TypedDict with Annotated reducers (`SingleChatState`, `ParallelOrchestratorState`, `DiscussionRankerState`, `LinkEnricherState`, `DataPreparationState`, `ContentGenerationState`)
- **Checkpointing**: MemorySaver (dev), SqliteSaver ready
- **Async**: Single event loop throughout (FastAPI -> LangGraph -> MongoDB, all native async)

### Key Source Directories

```
src/
├── main.py                        # FastAPI app entrypoint
├── config.py                      # Pydantic Settings (YAML + env)
├── constants.py                   # App-wide constants, community definitions
├── api/                           # FastAPI routes (newsletter_gen.py, schedules.py, async_batch_orchestration.py)
│   ├── sse/                       # Server-Sent Events streaming
│   └── observability/             # Runs browser & metrics endpoints (runs.py, metrics.py)
├── graphs/                        # LangGraph workflows
│   ├── single_chat_analyzer/      # Per-chat pipeline (graph.py, state.py, slm_prefilter.py)
│   ├── multi_chat_consolidator/   # Cross-chat consolidation (graph.py, consolidation_nodes.py)
│   └── subgraphs/                 # Shared subgraphs (discussion_ranker, link_enricher)
├── core/                          # Business logic
│   ├── ingestion/                 # Beeper/Matrix message extraction (extractors/, preprocessors/, decryption/)
│   ├── generation/                # Newsletter content generation (LLM) (generators/, image_describer)
│   ├── storage/                   # Persistent media storage (local filesystem, S3-ready)
│   ├── delivery/                  # Email (SendGrid, Gmail, SMTP2GO, Substack)
│   ├── retrieval/                 # History, mergers, rankers (history/, mergers/, rankers/)
│   └── slm/                       # Ollama SLM pre-filtering (provider.py, classifier.py)
├── custom_types/                  # Pydantic models (api_schemas.py, db_schemas.py, slm_schemas.py, sse_events.py, exceptions.py, common.py)
│   └── newsletter_formats/        # Format implementations (base.py, langtalks/, mcp_israel/)
├── db/                            # MongoDB layer (connection.py, run_tracker.py, node_persistence.py, indexes.py, cache.py)
│   └── repositories/              # Data access (base.py, discussions.py, newsletters.py, runs.py, messages.py, extraction_cache.py, room_id_cache.py)
├── scheduler/                     # APScheduler newsletter scheduling
├── background_jobs/               # Batch processing worker
├── utils/                         # Shared utilities (embedding/, llm/, tools/, validation.py, run_diagnostics.py)
└── observability/                 # Logging (Loki), tracing (Langfuse), metrics (Prometheus)
    ├── app/                       # Application logging (logger.py, context.py)
    ├── llm/                       # LLM tracing (langfuse_client.py, trace_context.py, evaluation.py)
    └── metrics/                   # Prometheus metrics (prometheus_client.py)
```

### Frontend (`ui/frontend/`)

React 19 + TypeScript + React Bootstrap + Zod validation. Key files:
- `src/constants/index.ts` - Community definitions (source of truth for chat names)
- `src/components/PeriodicNewsletterForm.tsx` - Main newsletter generation form
- `src/components/RunsBrowser.tsx` - Browse past newsletter runs
- `src/components/SchedulesPage.tsx` - Scheduled newsletter management
- `src/components/ProgressTracker.tsx` - Real-time pipeline progress display
- `src/components/DiagnosticReport.tsx` - Pipeline diagnostic reports
- `src/components/NewsletterDiscussionSelector.tsx` - Discussion selection UI
- `src/components/shared/` - Reusable components (AdvancedOptions, ChatSelector, LoadingSkeleton)
- `src/hooks/useNewsletterStream.ts` - SSE streaming hook
- `src/hooks/useSchedules.ts` - Schedule management hook
- `src/services/api.ts` - API client
- `src/utils/eventValidation.ts` - Zod schemas for SSE events

### Docker Services

| Service | Port | Purpose |
|---------|------|---------|
| app | 80 (nginx), 8000 (direct) | FastAPI + React frontend |
| mongodb + mongot | 27017 | Database + vector search |
| langfuse-server | 3001 | LLM observability UI |
| grafana | 3000 | Log visualization |
| n8n | 5678 | Workflow automation |
| ollama | 11434 | Local SLM inference |
| prometheus | 9090 | Metrics collection |
| loki | 3100 | Log aggregation |

## Community Structure

**Chat names are case-sensitive.** Source of Truth: `ui/frontend/src/constants/index.ts`

| `data_source_name` | Chat Names |
|---|---|
| `langtalks` | "LangTalks Community", "LangTalks Community 2", "LangTalks Community 3", "LangTalks Community 4", "LangTalks - Code Generation Agents", "LangTalks - English", "LangTalks - AI driven coding", "LangTalks AI-SDLC" |
| `mcp_israel` | "MCP Israel", "MCP Israel #2", "A2A Israel", "MCP-UI" |
| `n8n_israel` | "n8n israel - Main 1", "n8n israel - Main 2", "n8n Israel - Main 3" |
| `ai_transformation_guild` | "AI Transformation Guild" |
| `ail` | "AIL - AI Leaders Community" |

## API Usage

```bash
# Periodic newsletter (single chat)
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2025-10-01", "end_date": "2025-10-14", "data_source_name": "langtalks", "whatsapp_chat_names_to_include": ["LangTalks Community"], "desired_language_for_summary": "english", "summary_format": "langtalks_format", "consolidate_chats": false}'

# Multi-chat consolidated
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -d '{"consolidate_chats": true, "whatsapp_chat_names_to_include": ["MCP Israel", "MCP Israel #2"], ...}'

# Daily summaries (cross-day)
curl -X POST "http://localhost:8000/api/generate_daily_summaries" \
  -d '{"start_date": "2025-10-01", "end_date": "2025-10-14", ...}'
```

**Output**: `output/<source>_<start_date>_to_<end_date>/` with `per_chat/` and `consolidated/` subdirectories

### Key Parameters

| Parameter | Options | Default |
|-----------|---------|---------|
| `data_source_name` | `"langtalks"`, `"mcp_israel"`, `"n8n_israel"`, `"ai_transformation_guild"` | - |
| `summary_format` | `"langtalks_format"`, `"mcp_israel_format"` | - |
| `consolidate_chats` | `true`, `false` | `true` |
| `force_refresh_extraction` | `true`, `false` | `false` |
| `previous_newsletters_to_consider` | `0-20` | `5` |
| `enable_discussion_merging` | `true`, `false` | `true` |
| `similarity_threshold` | `"strict"`, `"moderate"`, `"aggressive"` | `"moderate"` |
| `enable_image_extraction` | `true`, `false` | `false` |

## Development Guidelines

### No Hardcoded Strings — Constants and Enums Only

**CRITICAL: Hardcoded string literals are BANNED in this codebase.** Every behavior-affecting string MUST be defined as a constant (`UPPER_SNAKE_CASE` in `constants.py`) or an enum member and imported — NEVER inlined.

This applies to:
- **State keys** (LangGraph state field names) → use `StateKeys` enum from `src/graphs/state_keys.py`
- **Node names** (LangGraph graph node identifiers) → use `NodeNames` enum from each graph's module
- **API endpoints, route paths**
- **DB collection/field names, cache keys, queue names**
- **Status values, category labels, format identifiers**
- **File paths, service identifiers, header names, error codes**
- **Any string used in conditional logic (`if x == "..."` is a code smell)**

**Where to define:**
- `src/constants.py` — app-wide constants and community definitions
- `src/graphs/state_keys.py` — all LangGraph state field name keys
- Per-graph `NodeNames` enum — graph node identifiers
- Domain-specific enums in `src/custom_types/`

**Enum rules:**
- Use `StrEnum` (Python 3.11+) for closed sets of related string values
- Code must NEVER reference `.value` on enum members — if `.value` is needed, the enum is missing a `__str__` override
- Plain `UPPER_SNAKE_CASE` constants for one-off strings

**Only exceptions:** user-facing display text, debug log messages, test fixtures.

Before writing ANY string literal in code, ask: "Does this string affect behavior?" If yes, it MUST be a constant or enum.

### Error Handling
**Fail-fast approach**: Break and stop with descriptive error logging. No silent fallbacks.

### Frontend Build Pitfall

**CRITICAL**: `API_BASE_URL` must be empty string (`""`) in:
1. `ui/frontend/src/constants/index.ts`
2. `docker-compose.yml` build args

NEVER set to `"/api"` or `"http://localhost:8000"` (causes double `/api/api/` prefix).

### Beeper Message Decryption

**Fallback Chain** (automatic):
1. Server-Side Backup (if `BEEPER_RECOVERY_CODE` set)
2. Persistent Session (`./secrets/beeper_matrix_store/`)
3. Manual Export Keys (`./secrets/decrypted-keys.json`)

**Setup**: `.venv/bin/python ui/cli/beeper_setup/setup_recovery_code.py`

Docs: `knowledge/beeper/HOW_TO_EXPORT_KEYS.md`

### SLM Integration (Optional)

Ollama-based message pre-filtering to reduce LLM API costs (15-30%). Set `SLM_ENABLED=true` in `.env`.

```bash
# Pull model (one-time, after docker compose up)
docker exec langrag-ollama ollama pull phi3:3.8b-mini-instruct-4k-q4_K_M
```

### Scheduled Newsletters

APScheduler (built into FastAPI) checks MongoDB `scheduled_newsletters` collection every minute. Configure via Web UI "Schedules" tab or API (`POST /api/schedules`).

Docs: `knowledge/n8n/SCHEDULED_NEWSLETTER.md`

### LinkedIn Integration (n8n)

Set `"create_linkedin_draft": true` in API request. Requires n8n setup with LinkedIn OAuth.

Docs: `knowledge/n8n/LINKEDIN_INTEGRATION.md`

### Newsletter Defaults

Default parameters for `/newsletter-generate` and `/newsletter-iterate`. Override any of these per-request.

| Parameter | Default |
|-----------|---------|
| `data_source_name` | `langtalks` |
| `desired_language_for_summary` | `hebrew` |
| `output_actions` | `["save_local", "send_email"]` |
| `email_recipients` | `["eladlaor88@gmail.com"]` |
| `consolidate_chats` | `true` |
| `hitl_selection_timeout_minutes` | `0` |

When "all groups" is specified without a community, default to all langtalks groups.

Iteration methodology documented in: `knowledge/newsletter/ITERATION_METHODOLOGY.md`

### Claude Code Skills

- `/newsletter-generate` - Generate a newsletter for any community with sensible defaults
- `/news-new-v` - Generate a new newsletter version using Opus directly (no pipeline re-run, no OpenAI cost)
- `/add-whatsapp-community` - Automates adding new WhatsApp communities (updates backend, frontend, types, docs)
- `/pipeline-test` - Iterative self-healing test runner
- `/extract-substack-newsletters` - Substack newsletter extraction
- `/push-public` - Nuclear squash-push of entire repo to public remote (single v1.0.0 commit)
- `/push-public-update` - Incremental delta push to public remote with version tags, changelog, and GitHub Releases

Skills use single-file pattern: one `SKILL.md` per skill, no README files.

## Key Documentation

- **Developer Guide** (architecture + LangGraph tutorial): `knowledge/architecture/DEVELOPER_GUIDE.md`
- **SLM Integration**: `knowledge/plans/SLM_INTEGRATION.md`
- **Delivery Destinations**: `knowledge/plans/DELIVERY_DESTINATIONS_PLAN.md`
- **API Monolith Split**: `knowledge/plans/API_MONOLITH_SPLIT_PLAN.md`
- **Diagnostics**: `knowledge/plans/DIAGNOSTICS_IMPLEMENTATION_PLAN.md`
- **Testing Guide**: `knowledge/testing/QUICK_START.md`
- **E2E Testing**: `knowledge/testing/e2e_pipeline_testing.md`
- **Beeper Extraction**: `knowledge/beeper/beeper_extraction_guide.md`
- **Observability**: `knowledge/observability/OBSERVABILITY_OVERVIEW.md`
- **Database Schema**: `knowledge/mongodb/DATABASE_SCHEMA.md`
- **Newsletter Iteration**: `knowledge/newsletter/ITERATION_METHODOLOGY.md`
- **Audit Recommendations**: `knowledge/AUDIT_RECOMMENDATIONS.md`
- **Changelog**: `knowledge/CHANGELOG.md`

## Troubleshooting

- **Web UI not loading**: `docker compose ps` to check services, `docker compose logs -f` for errors
- **Newsletter generation fails**: Verify chat names (case-sensitive), check date range has messages, try `force_refresh_extraction: true`
- **Message decryption**: See `knowledge/beeper/HOW_TO_EXPORT_KEYS.md`
- **Frontend double-prefix**: Ensure `API_BASE_URL` is `""` (empty string), never `"/api"`
