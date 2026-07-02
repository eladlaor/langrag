/**
 * Constants for the public podcast-MCP access page (langrag.ai/podcasts).
 *
 * This is a standalone PUBLIC landing (NOT behind the app login gate) where
 * external AI engineers request an MCP API key to query the LangTalks podcast
 * (and future podcasts) from their own agent. See
 * knowledge/plans/PODCAST_MCP_PUBLIC_ACCESS.md.
 *
 * Every behavior-affecting string here is a constant — the SPA route, the
 * verify query-param name (the contract with the backend email template), the
 * hosted MCP URL, and the frozen public MCP tool names.
 */

// SPA route that serves this page. nginx `try_files ... /index.html` makes it
// reachable by direct URL; index.tsx branches on this pathname before the auth
// gate so strangers never see the login screen.
export const PODCAST_PAGE_PATH = "/podcasts";

// The verification email links back here as `/podcasts?token=...`. The param
// name is the behavioral contract with the backend email template.
export const PODCAST_VERIFY_TOKEN_PARAM = "token";

// Hosted MCP endpoint (SSE transport). One endpoint for ALL podcasts — never a
// per-podcast host. The `/sse` suffix is the transport path clients connect to.
export const MCP_BASE_URL = "https://mcp.langrag.ai";
export const MCP_SSE_URL = `${MCP_BASE_URL}/sse`;

// Placeholder token users replace with their issued key inside setup snippets.
export const API_KEY_PLACEHOLDER = "YOUR_KEY";

// Named MCP server key used in the copy-paste client configs.
export const MCP_SERVER_NAME = "podcasts";

// Frozen public MCP tool surface (search-only). Names are the contract — they
// live in every user's client config, so they must never change.
export const MCP_TOOLS = [
  {
    name: "search_podcasts",
    signature: "search_podcasts(query, podcast?, date_start?, date_end?, top_k?)",
    description:
      "Retrieve dated, cited transcript chunks matching a query. Omit `podcast` to search all shows, or pass a slug (e.g. \"langtalks\") to scope it. Optional ISO date filters and top_k.",
  },
  {
    name: "list_podcasts",
    signature: "list_podcasts()",
    description:
      "Discover which podcasts are queryable. New shows appear here automatically — no client change needed.",
  },
] as const;

/**
 * Client setup snippets. `{KEY}` is substituted with the issued key when one is
 * available (else API_KEY_PLACEHOLDER); `{URL}` is substituted with the endpoint
 * the backend returned on verify (result.mcp_url), falling back to MCP_SSE_URL
 * when absent — so staging/prod can differ without a frontend rebuild (F3).
 */
export const SETUP_SNIPPETS = [
  {
    id: "claude-code",
    label: "Claude Code",
    language: "bash",
    template: `claude mcp add --transport sse ${MCP_SERVER_NAME} {URL} --header "Authorization: Bearer {KEY}"`,
  },
  {
    id: "cursor",
    label: "Cursor",
    language: "json",
    template: `{
  "mcpServers": {
    "${MCP_SERVER_NAME}": {
      "url": "{URL}",
      "headers": { "Authorization": "Bearer {KEY}" }
    }
  }
}`,
  },
  {
    id: "generic-sse",
    label: "Generic MCP (SSE)",
    language: "json",
    template: `{
  "mcpServers": {
    "${MCP_SERVER_NAME}": {
      "type": "sse",
      "url": "{URL}",
      "headers": { "Authorization": "Bearer {KEY}" }
    }
  }
}`,
  },
] as const;

// FAQ content. User-facing display text (documented exception to the
// no-hardcoded-strings rule), colocated for a single source of truth.
export const PODCAST_FAQ = [
  {
    q: "Does this answer my questions for me?",
    a: "No. It is search-only: the MCP returns dated, cited transcript chunks. Your own agent's LLM reads those chunks and writes the answer. You pay only your own model's tokens — never our generation cost.",
  },
  {
    q: "Are there rate limits or quotas?",
    a: "Yes. Requests are rate-limited and each key has a usage quota. Heavy or abusive traffic will be throttled.",
  },
  {
    q: "Can my key be revoked?",
    a: "Yes. Keys are revocable at any time on abuse. Treat your key as a secret and do not share it.",
  },
  {
    q: "Which shows can I query?",
    a: "Today the LangTalks podcast, with more to come. Call list_podcasts() from your agent to see the live catalog — new shows become queryable with the same key and no config change.",
  },
] as const;

// Structured-logging component tag for this page.
export const PODCAST_LOG_COMPONENT = "PodcastPortal";
