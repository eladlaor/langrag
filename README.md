<div align="center">

  <img src="docs/figures/images/langrag_banner.png" alt="LangRAG: Recapping All Groups" width="300">

  <h2>⭐ Chosen by AI community leaders since 2024 ⭐</h2>

  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
  <a href="https://docs.docker.com/compose/"><img src="https://img.shields.io/badge/docker-compose-2496ED.svg" alt="Docker Compose"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-async-009688.svg" alt="FastAPI"></a>
  <a href="https://langchain-ai.github.io/langgraph/"><img src="https://img.shields.io/badge/LangGraph-1.0+-black.svg" alt="LangGraph"></a>
  <a href="https://www.mongodb.com/"><img src="https://img.shields.io/badge/MongoDB-8.0-47A248.svg" alt="MongoDB"></a>
  <a href="https://langfuse.com/"><img src="https://img.shields.io/badge/Langfuse-observability-F4B400.svg" alt="Langfuse"></a>
  <img src="https://img.shields.io/badge/LLM_Batching-orchestration-412991.svg" alt="LLM Batching Orchestration">
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/Ollama-SLM-white.svg" alt="Ollama SLM"></a>
  <a href="https://www.anthropic.com/"><img src="https://img.shields.io/badge/Anthropic-Claude-D97757.svg" alt="Anthropic"></a>
  <a href="https://creativecommons.org/licenses/by-nc/4.0/"><img src="https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey.svg" alt="CC BY-NC 4.0"></a>

</div>

<br>

<div align="center">
  <img src="docs/figures/pipeline_overview/pipeline_overview.gif" alt="LangRAG pipeline overview - animated" width="800">
</div>

<br>

## Table of Contents

- [Overview](#why)
  - [Why](#why)
  - [What](#what)
  - [How](#how)
- [Chosen By Leading AI-Engineering Communities](#chosen-by-leading-ai-engineering-communities)
  - [LangTalks](#langtalks)
  - [API: AI Protocols Israel](#api--ai-protocols-israel)
  - [n8n Israel](#n8n-israel)
  - [AI Transformation Guild](#ai-transformation-guild)
  - [AIL - AI Leaders](#ail---ai-leaders)
- [How It Works](#how-it-works)
  - [Pipeline Overview](#pipeline-overview)
  - [What Gives This Solution an Edge](#what-gives-this-solution-an-edge)
  - [Why Reply Correlation Matters](#why-reply-correlation-matters)
- [Setup](#setup)
  - [Getting Started](#getting-started)
  - [User Interfaces](#user-interfaces)
  - [API Examples](#api-usage)
  - [Configuration Reference](#configuration-reference)
  - [Adding Your Own WhatsApp Group](#adding-your-own-whatsapp-group)
- [Be a Friend](#be-a-friend)
  - [Improving LangRAG](#improving-langrag)
  - [Supporting LangRAG](#supporting-langrag)

---

### Why

If you're an AI engineer you're in FOMO.<br>
**The good news:** There are some great communities (support groups:) you can join.<br>Real people, real challenges, daily discussions on Whatsapp.<br>
Separating noise from nuance, tacky from techy, and whatever 3rd wordplay I can fit in here you got the idea.<br>
**The bad news:** the messages are too valuable to miss, but waaaaaaaaaaay too many to keep up with.

### What

Generating worth-your-time newsletters for AI engineers, carefully distilled from thousands of WhatsApp messages.

### How

LangRAG uses Beeper for the crucial first phase: extracting WhatsApp messages along with rich metadata.<br> Then, LangRAG runs through async LangGraph pipelines that process and analyze multiple group-chats in parallel, applying MMR and reranking to produce structured and relevant content.<br>The analysis is **deep, highly-configurable, and cost-optimized**.<br>Full observability across tracing, evals, metrics and logs.

---

## Chosen By Leading AI-Engineering Communities

### LangTalks

<img src="docs/figures/images/langtalks.jpg" alt="LangTalks" width="100" align="left" style="margin-right: 16px; border-radius: 12px;">

![8 WhatsApp groups](https://img.shields.io/badge/-8_WhatsApp_groups-555?logo=whatsapp&logoColor=25D366)

Israel's largest AI-engineering community.

Founded by [Lee Twito](https://www.linkedin.com/in/lee-twito/) & [Gal Peretz](https://www.linkedin.com/in/gal-peretz/)

[Join the community 🍕🍻](https://langtalks.ai/)

<br clear="left">

<hr width="50%" align="center">

### API: AI Protocols Israel

<img src="docs/figures/images/mcp_israel.jpg" alt="API: AI Protocols Israel" width="100" align="left" style="margin-right: 16px; border-radius: 12px;">

![4 WhatsApp groups](https://img.shields.io/badge/-4_WhatsApp_groups-555?logo=whatsapp&logoColor=25D366)

The go-to community for MCP, A2A, MCP-UI, and emerging AI protocol standards.

Founded by [Gilad Shoham](https://www.linkedin.com/in/shohamgilad/), [Leon Melamud](https://www.linkedin.com/in/leon-melamud/) & [Adir Duchan](https://www.linkedin.com/in/adir-duchan/)

[Join the community 🍕🍻](https://www.linkedin.com/company/106916433/)

<br clear="left">

<hr width="50%" align="center">

### n8n Israel

<img src="docs/figures/images/n8n_israel.jpg" alt="n8n Israel" width="100" align="left" style="margin-right: 16px; border-radius: 12px;">

![3 WhatsApp groups](https://img.shields.io/badge/-3_WhatsApp_groups-555?logo=whatsapp&logoColor=25D366)

Israel's workflow automation community.

Founded by [Elay Guez](https://www.linkedin.com/in/elay-g/), [Gilad Shoham](https://www.linkedin.com/in/shohamgilad/) & [Leon Melamud](https://www.linkedin.com/in/leon-melamud/)

[Join the community 🍕🍻](https://www.linkedin.com/company/israel-n8n/)

<br clear="left">

<hr width="50%" align="center">

### AI Transformation Guild

<img src="docs/figures/images/ai_transformation.jpg" alt="AI Transformation Guild" width="100" align="left" style="margin-right: 16px; border-radius: 12px;">

![1 WhatsApp group](https://img.shields.io/badge/-1_WhatsApp_group-555?logo=whatsapp&logoColor=25D366)

A community for those who are leading AI transformation processes in mid-to-large scale organizations. 

Founded by [Gilad Shoham](https://www.linkedin.com/in/shohamgilad/), [Leon Melamud](https://www.linkedin.com/in/leon-melamud/), [Tomer Shahar](https://www.linkedin.com/in/tommer-shahar/) & [Oren Melamed](https://www.linkedin.com/in/orenmelamed/)

[Apply to join](https://docs.google.com/forms/d/e/1FAIpQLScU8vIRAG_QlMqX3zlbhVc8etyVpeZcjb7xbe__sA2ajKp2sQ/viewform)

<br clear="left">

<hr width="50%" align="center">

### AIL - AI Leaders

<img src="docs/figures/images/ai_leaders.jpg" alt="AIL - AI Leaders" width="100" align="left" style="margin-right: 16px; border-radius: 12px;">

![1 WhatsApp group](https://img.shields.io/badge/-1_WhatsApp_group-555?logo=whatsapp&logoColor=25D366)

A community for AI\Data Leads. 

Founded by [Gilad Shoham](https://www.linkedin.com/in/shohamgilad/), [Leon Melamud](https://www.linkedin.com/in/leon-melamud/), [Tomer Shahar](https://www.linkedin.com/in/tommer-shahar/) & [Oren Melamed](https://www.linkedin.com/in/orenmelamed/)

[Apply to join](https://docs.google.com/forms/d/e/1FAIpQLScU8vIRAG_QlMqX3zlbhVc8etyVpeZcjb7xbe__sA2ajKp2sQ/viewform)

<br clear="left">

---

## How It Works

### Pipeline Overview

<div align="center">
  <img src="docs/figures/pipeline_overview/pipeline_overview.png" alt="LangRAG pipeline overview - full diagram" width="800">
</div>

---

### What Gives this Solution an Edge

| Feature | How | Impact |
|---------|-----|--------|
| Image Understanding | Vision model describes shared images, context injected into generation | Newsletters reflect visual content, not just text |
| Reply Correlation | Matrix `m.relates_to` metadata preserved through Beeper extraction | Precise discussion separation - no timestamp guessing |
| MMR Diversity Ranking | Multi-factor scoring + Maximal Marginal Relevance | Quality-diversity balance |
| Human-in-the-Loop | Two-phase pipeline with Web UI discussion selector | Editorial control over final newsletter content |
| Batch API | JSONL serialization, async polling, exponential backoff | 50% cost reduction |
| SLM Pre-filtering | Configurable local SLM classifies KEEP/FILTER/UNCERTAIN before LLM | 15-30% additional savings |
| SLM Semantic Enrichment | Fine-tuned DeBERTa-v3 model tags messages with 15 semantic labels for ranking | Richer discussion scoring signals |
| Hybrid Anti-Repetition | Embedding cosine similarity + LLM validation vs. last N editions | No repetition of content from previous N newsletters |
| Smart Discussion Merging | Configurable similarity thresholds + LLM validation | Better handling of cross-group similar discussions |
| Full Observability | Langfuse + Prometheus + Loki/Grafana, all fail-soft | Production monitoring |
| Link Enrichment | Auto-fetch URLs, non-destructive markdown insertion | References for further learning |
| Configurable Output Formats | Format plugins with custom structure, sections, and editorial style | JSON, Markdown, and HTML per community |
| Multi-Channel Delivery | Email (SendGrid, Gmail, SMTP2GO), LinkedIn draft (n8n), webhooks | One pipeline, multiple destinations |

#### Why reply correlation matters

Standard WhatsApp export tools lose reply metadata. Without it, a reply referring to discussion X can easily be classified into discussion Y, if discussion Y was ongoing between the last message of discussion X, and until someone had the time to read and reply to discussion X (which can even be a whole day after). [Beeper](https://www.beeper.com/) bridges WhatsApp to Matrix, exposing `m.in_reply_to` on every reply. LangRAG uses this for accurate discussion separations.

---

## Setup

### Getting Started

#### Prerequisites

- Docker and Docker Compose
- OpenAI/Anthropic API key
- Beeper account with WhatsApp bridge configured

#### 1. Beeper Setup

LangRAG reads WhatsApp messages through [Beeper](https://www.beeper.com/), which bridges WhatsApp to the Matrix protocol.

See the full setup guide: **[docs/setup/SETUP_BEEPER.md](docs/setup/SETUP_BEEPER.md)**

Quick version:
1. Create a Beeper account and link your WhatsApp
2. Export your E2E encryption keys from the Beeper Web UI
3. Place the exported keys file at `./secrets/exported_keys/element-keys.txt`
4. Set `BEEPER_EMAIL`, `BEEPER_PASSWORD`, and `BEEPER_EXPORT_PASSWORD` in `.env`

#### 2. Clone and Configure

```bash
git clone https://github.com/eladlaor/langrag.git
cd langrag

cp .env.example .env
# Edit .env | at minimum set: OPENAI_API_KEY or ANTHROPIC_API_KEY, BEEPER_USERNAME, BEEPER_PASSWORD

# Generate required secrets
echo "LANGFUSE_AUTH_SECRET=$(openssl rand -base64 32)" >> .env
echo "LANGFUSE_SALT=$(openssl rand -base64 32)" >> .env
echo "LANGFUSE_DB_PASSWORD=$(openssl rand -base64 32)" >> .env
```

See [Configuration Reference](#configuration-reference) for the full list of parameters and environment variables.

#### 3. Start Services

```bash
docker compose up -d
```

That's it.

### User Interfaces

| Service | URL | Purpose |
|---------|-----|---------|
| Web UI | http://localhost | Newsletter generation, scheduling, run browser |
| CLI | `curl` / any HTTP client | Direct API access for scripting and automation |
| API docs | http://localhost/docs | Interactive FastAPI Swagger docs |
| LangGraph Studio | printed by `langgraph dev` | Visual graph inspector for nodes, edges, and subgraphs |
| Langfuse | http://localhost:3001 | LLM tracing, prompt management, cost tracking |
| Grafana | http://localhost:3000 | Log visualization and dashboards |

### API Usage

```bash
# Single chat newsletter
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-10-01",
    "end_date": "2025-10-14",
    "data_source_name": "langtalks",
    "whatsapp_chat_names_to_include": ["LangTalks Community"],
    "desired_language_for_summary": "english",
    "summary_format": "langtalks_format",
    "consolidate_chats": false
  }'

# Multi-chat consolidated newsletter
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-10-01",
    "end_date": "2025-10-14",
    "data_source_name": "mcp_israel",
    "whatsapp_chat_names_to_include": ["MCP Israel", "MCP Israel #2"],
    "consolidate_chats": true
  }'
```

Output is written to `output/<source>_<start_date>_to_<end_date>/` with `per_chat/` and `consolidated/` subdirectories.

#### LinkedIn Draft Automation

Add `"create_linkedin_draft": true` to any newsletter API request to automatically create a LinkedIn draft post from the consolidated newsletter. Requires a one-time n8n + LinkedIn OAuth setup.

See: **[docs/setup/SETUP_LINKEDIN_WEBHOOK.md](docs/setup/SETUP_LINKEDIN_WEBHOOK.md)**

### Configuration Reference

#### Generation Parameters

| Parameter | Description | Options | Default |
|-----------|-------------|---------|---------|
| `data_source_name` | Which community to generate a newsletter for | `langtalks`, `mcp_israel`, `n8n_israel`, `ai_transformation_guild`, `ail` | required |
| `consolidate_chats` | Merge results from multiple chats into a single newsletter | `true` / `false` | `true` |
| `force_refresh_extraction` | Re-extract messages from Beeper, ignoring cached data | `true` / `false` | `false` |
| `previous_newsletters_to_consider` | Number of past newsletters checked for anti-repetition | `0`-`20` | `5` |
| `enable_discussion_merging` | Merge similar discussions across different chats | `true` / `false` | `true` |
| `similarity_threshold` | How aggressively to merge similar discussions | `strict` / `moderate` / `aggressive` | `moderate` |
| `summary_format` | Newsletter template and editorial style | `langtalks_format`, `mcp_israel_format` | required |
| `enable_image_extraction` | Extract and describe shared images using a vision model | `true` / `false` | `false` |
| `create_linkedin_draft` | Auto-create a LinkedIn draft post via n8n | `true` / `false` | `false` |

#### Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | LLM provider API access (one required) |
| `BEEPER_USERNAME` / `BEEPER_PASSWORD` | Beeper authentication |
| `BEEPER_HOMESERVER` | Matrix homeserver (default: `beeper.local`) |
| `BEEPER_RECOVERY_CODE` | Optional, enables server-side key backup |
| `SLM_ENABLED` | Enable Ollama SLM pre-filtering (`true`/`false`) |
| `SLM_ENRICHMENT_ENABLED` | Enable DeBERTa semantic enrichment for ranking (`true`/`false`) |
| `MONGODB_URI` | MongoDB connection string |
| `EMAIL_PROVIDER` | Email delivery provider (`gmail` / `sendgrid`) |
| `DEFAULT_EMAIL_RECIPIENT` | Default recipient when `send_email` is triggered without explicit recipients |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | Gmail SMTP credentials (use app password, not account password) |
| `SENDGRID_API_KEY` | SendGrid API key (for production/high-volume delivery) |
| `EMAIL_SENDER_ADDRESS` | Verified sender address used in outgoing newsletter emails |

---

<details>
<summary><strong>Docker Services</strong></summary>

| Service | Port | Purpose |
|---------|------|---------|
| app | 80 (nginx), 8000 (direct) | FastAPI + React frontend |
| mongodb | 27017 | Database + vector search |
| langfuse-server | 3001 | LLM observability |
| grafana | 3000 | Log visualization |
| n8n | 5678 | Workflow automation (LinkedIn drafts) |
| ollama | 11434 | Local SLM inference |
| prometheus | 9090 | Metrics collection |
| loki | 3100 | Log aggregation |

</details>

---

### Adding Your Own WhatsApp Group

#### Self Host

Adding a community takes a few constant definitions and a Docker rebuild:

1. **Backend** | Add the community to `src/constants.py` (data source name, chat list, format mapping)
2. **Frontend** | Add the community to `ui/frontend/src/constants/index.ts`

> **Note:** Chat names are case-sensitive and must match Beeper/Matrix room names exactly.

#### Or Contact Me

Feel free to [connect](https://www.linkedin.com/in/elad-laor-1b1383250/) if you'd like me to hook this up for you. If you're leading an AI-engineering community, I'll be happy to add it to the system's periodic runs, and generate custom-format newsletters for your community. 

---

## Be a Friend

### Improving LangRAG

Feature request? Optimization suggestion? Bug report? [Open an issue](https://github.com/eladlaor/langrag/issues). Thanks!

### Supporting LangRAG

If you're feeling generous, please consider clicking that "Star" thingy at the top ⭐
