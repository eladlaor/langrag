/**
 * useAgentStream — SSE consumer for /api/agent/chat/stream and
 * /api/agent/chat/resume.
 *
 * Drives a reducer with the documented `AgentEventType` taxonomy.
 * Modeled on the existing useNewsletterStream pattern but consuming a
 * different event vocabulary (no shared parser — the event payloads
 * are different enough that abstraction would obscure both).
 */

import { useCallback, useReducer, useRef } from "react";

import { API_BASE_URL, FETCH_CREDENTIALS, SESSION_EXPIRED_EVENT } from "../constants";
import {
  AgentEventType,
  ArtifactPanelPayload,
  InterruptPayload,
  ToolCallChipState,
} from "../types/agent";

export interface AgentStreamState {
  isStreaming: boolean;
  assistantText: string;
  toolCalls: Record<string, ToolCallChipState>; // keyed by call_id
  artifactPanels: ArtifactPanelPayload[];
  pendingInterrupt: InterruptPayload | null;
  error: string | null;
  done: boolean;
}

const INITIAL_STATE: AgentStreamState = {
  isStreaming: false,
  assistantText: "",
  toolCalls: {},
  artifactPanels: [],
  pendingInterrupt: null,
  error: null,
  done: false,
};

type Action =
  | { type: "stream_started" }
  | { type: "token"; token: string }
  | {
      type: "tool_started";
      call_id: string;
      tool: string;
      args: unknown;
    }
  | {
      type: "tool_finished";
      call_id: string;
      status: "success" | "error";
      result_summary: string;
    }
  | { type: "artifact_panel"; payload: ArtifactPanelPayload }
  | { type: "interrupt_required"; payload: InterruptPayload }
  | { type: "error"; message: string }
  | { type: "done" }
  | { type: "reset" };

export function agentStreamReducer(
  state: AgentStreamState,
  action: Action
): AgentStreamState {
  switch (action.type) {
    case "stream_started":
      return { ...INITIAL_STATE, isStreaming: true };
    case "token":
      return { ...state, assistantText: state.assistantText + action.token };
    case "tool_started":
      return {
        ...state,
        toolCalls: {
          ...state.toolCalls,
          [action.call_id]: {
            call_id: action.call_id,
            tool: action.tool,
            args: action.args,
            status: "running",
          },
        },
      };
    case "tool_finished":
      return {
        ...state,
        toolCalls: {
          ...state.toolCalls,
          [action.call_id]: {
            ...(state.toolCalls[action.call_id] || {
              call_id: action.call_id,
              tool: "",
              args: {},
            }),
            status: action.status,
            result_summary: action.result_summary,
          },
        },
      };
    case "artifact_panel":
      return {
        ...state,
        artifactPanels: [...state.artifactPanels, action.payload],
      };
    case "interrupt_required":
      return { ...state, pendingInterrupt: action.payload };
    case "error":
      return { ...state, error: action.message, isStreaming: false };
    case "done":
      return { ...state, isStreaming: false, done: true };
    case "reset":
      return INITIAL_STATE;
    default:
      return state;
  }
}

/**
 * Parse one SSE event chunk ("event: X\ndata: {...}") and dispatch the
 * matching action.
 *
 * Exported so it can be unit-tested against synthetic chunks.
 */
export function dispatchSSEChunk(
  chunk: string,
  dispatch: (a: Action) => void
): void {
  let eventType: string | undefined;
  let data: unknown;
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event: ")) {
      eventType = line.slice("event: ".length).trim();
    } else if (line.startsWith("data: ")) {
      try {
        data = JSON.parse(line.slice("data: ".length));
      } catch {
        data = line.slice("data: ".length);
      }
    }
  }
  if (!eventType) {
    return;
  }
  const d = (data ?? {}) as Record<string, unknown>;
  switch (eventType) {
    case AgentEventType.Token:
      dispatch({ type: "token", token: String(d.token ?? "") });
      return;
    case AgentEventType.ToolCallStarted:
      dispatch({
        type: "tool_started",
        call_id: String(d.call_id ?? ""),
        tool: String(d.tool ?? ""),
        args: d.args,
      });
      return;
    case AgentEventType.ToolCallFinished:
      dispatch({
        type: "tool_finished",
        call_id: String(d.call_id ?? ""),
        status: (d.status === "error" ? "error" : "success") as
          | "success"
          | "error",
        result_summary: String(d.result_summary ?? ""),
      });
      return;
    case AgentEventType.ArtifactPanel:
      dispatch({ type: "artifact_panel", payload: d as unknown as ArtifactPanelPayload });
      return;
    case AgentEventType.InterruptRequired:
      dispatch({
        type: "interrupt_required",
        payload: d as unknown as InterruptPayload,
      });
      return;
    case AgentEventType.Error:
      dispatch({ type: "error", message: String(d.error ?? "unknown") });
      return;
    case AgentEventType.Done:
      dispatch({ type: "done" });
      return;
  }
}

export interface UseAgentStream {
  state: AgentStreamState;
  startChat: (sessionId: string, message: string, apiKey: string) => Promise<void>;
  resume: (sessionId: string, decision: string, apiKey: string) => Promise<void>;
  reset: () => void;
}

export function useAgentStream(): UseAgentStream {
  const [state, dispatch] = useReducer(agentStreamReducer, INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const drive = useCallback(
    async (path: string, body: unknown, apiKey: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: "stream_started" });
      try {
        const resp = await fetch(`${API_BASE_URL}${path}`, {
          method: "POST",
          credentials: FETCH_CREDENTIALS,
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": apiKey,
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        if (!resp.ok) {
          if (resp.status === 401) {
            window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
          }
          dispatch({ type: "error", message: `HTTP ${resp.status}` });
          return;
        }
        const reader = resp.body?.getReader();
        if (!reader) {
          dispatch({ type: "error", message: "no response body" });
          return;
        }
        const decoder = new TextDecoder();
        let buffer = "";
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          // SSE events are separated by a blank line ("\n\n").
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            if (part.trim()) {
              dispatchSSEChunk(part, dispatch);
            }
          }
        }
        if (buffer.trim()) {
          dispatchSSEChunk(buffer, dispatch);
        }
      } catch (err) {
        if ((err as { name?: string })?.name === "AbortError") {
          return;
        }
        dispatch({
          type: "error",
          message:
            err instanceof Error ? err.message : "stream failed",
        });
      }
    },
    []
  );

  const startChat = useCallback(
    (sessionId: string, message: string, apiKey: string) =>
      drive("/api/agent/chat/stream", { session_id: sessionId, message }, apiKey),
    [drive]
  );

  const resume = useCallback(
    (sessionId: string, decision: string, apiKey: string) =>
      drive(
        "/api/agent/chat/resume",
        { session_id: sessionId, decision },
        apiKey
      ),
    [drive]
  );

  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  return { state, startChat, resume, reset };
}
