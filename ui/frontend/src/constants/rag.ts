/**
 * RAG feature constants
 */

export const RAG_CONTENT_SOURCES = [
  { value: "podcast", label: "Podcasts" },
  { value: "newsletter", label: "Newsletters" },
  { value: "chat_message", label: "Chat Messages" },
] as const;

export const RAG_SSE_EVENTS = {
  TOKEN: "token",
  CITATION: "citation",
  DONE: "done",
  ERROR: "error",
  EVALUATION_SCORE: "evaluation_score",
} as const;

export const RAG_API_ROUTES = {
  CHAT_STREAM: "/api/rag/chat/stream",
  SESSIONS: "/api/rag/sessions",
  INGEST_PODCASTS: "/api/rag/ingest/podcasts",
  INGEST_PODCASTS_SCAN: "/api/rag/ingest/podcasts/scan",
  SOURCES_STATS: "/api/rag/sources/stats",
  EVALUATIONS: "/api/rag/evaluations",
} as const;
