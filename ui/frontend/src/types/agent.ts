/**
 * Agent chat types — mirror of the backend `AgentEventType` enum and the
 * tool / memory / session payload shapes from `src/api/agent_chat.py`.
 *
 * Keep these in lockstep with the backend definitions. Drift here would
 * show up as silent silent SSE event mishandling on the client.
 */

export enum AgentEventType {
  Token = "token",
  ToolCallStarted = "tool_call_started",
  ToolCallFinished = "tool_call_finished",
  ArtifactPanel = "artifact_panel",
  InterruptRequired = "interrupt_required",
  MemoryWritten = "memory_written",
  BudgetWarning = "budget_warning",
  Error = "error",
  Done = "done",
}

export interface AgentSSEEvent {
  event: AgentEventType;
  data: Record<string, unknown>;
}

export interface AgentSessionSummary {
  session_id: string;
  title: string;
  community_context: string | null;
  created_at: string;
  last_message_at: string;
  message_count: number;
}

export interface AgentMemoryItem {
  memory_id: string;
  namespace: "semantic" | "episodic" | "procedural" | string;
  content: string;
  importance: number;
}

export interface CreateSessionRequest {
  title?: string;
  community_context?: string | null;
}

export interface CreateSessionResponse {
  session_id: string;
  created_at: string;
  title: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
}

export interface ChatResponse {
  session_id: string;
  assistant_message: string;
  tool_calls: Array<{ name: string; args: unknown; id: string }>;
  artifact_events: Array<Record<string, unknown>>;
  memories_loaded: number;
}

export interface ToolCallChipState {
  call_id: string;
  tool: string;
  args: unknown;
  status: "running" | "success" | "error";
  result_summary?: string;
}

export interface ArtifactPanelPayload {
  component: string;
  props: Record<string, unknown>;
}

export interface InterruptPayload {
  kind: string;
  action: string;
  args: Record<string, unknown>;
}

export interface RagPreferences {
  mmr_lambda: number;
  enable_mmr_diversity: boolean;
}

// Agent API key management (cookie-gated /api/users/me/agent-keys). The
// plaintext is present only on the issue response, never on the listing.
export interface AgentApiKeyIssued {
  key_id: string;
  name: string;
  plaintext: string;
}

export interface AgentApiKeySummary {
  key_id: string;
  name: string;
  enabled: boolean;
  created_at: string | null;
  last_used_at: string | null;
}
