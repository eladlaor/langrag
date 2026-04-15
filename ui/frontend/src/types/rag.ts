/**
 * TypeScript types for RAG conversation feature
 */

export interface RAGSession {
  session_id: string;
  title: string | null;
  content_sources: string[];
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

export interface RAGCitation {
  index: number;
  chunk_id: string;
  source_type: string;
  source_title: string;
  snippet: string;
  search_score: number;
  metadata: Record<string, unknown>;
}

export interface RAGMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  citations?: RAGCitation[];
  evaluation_id?: string | null;
  created_at?: string;
}

export interface RAGSessionDetail extends RAGSession {
  messages: RAGMessage[];
}

export interface RAGChatRequest {
  session_id: string | null;
  query: string;
  content_sources: string[];
}

export interface RAGSourceStats {
  source_type: string;
  chunk_count: number;
}

export interface RAGEvaluation {
  evaluation_id: string;
  session_id: string;
  scores: Record<string, number>;
  overall_passed: boolean;
  status: string;
  duration_ms: number;
}

export interface RAGChatState {
  status: "idle" | "streaming" | "error";
  currentAnswer: string;
  citations: RAGCitation[];
  error: string | null;
  sessionId: string | null;
}
