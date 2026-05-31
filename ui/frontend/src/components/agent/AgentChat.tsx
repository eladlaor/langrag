/**
 * AgentChat — split-pane container for the agentic chatbot.
 *
 * Left: message thread + composer + tool-call chips.
 * Right: ArtifactPanelRouter (progress, runs, drafts).
 *
 * The API key is sourced from props (set by the page that mounts the
 * component, typically from an environment-aware auth context). The
 * v1.14.0 surface is intentionally minimal — once the backend
 * stabilizes we can rework styling and add streaming-keyboard-input
 * niceties.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE_URL } from "../../constants";
import { useAgentStream } from "../../hooks/useAgentStream";
import {
  AgentSessionSummary,
  CreateSessionResponse,
} from "../../types/agent";
import { ArtifactPanelRouter } from "./ArtifactPanelRouter";
import { InterruptDialog } from "./InterruptDialog";
import { MemoryInspector } from "./MemoryInspector";
import { ToolCallChip } from "./ToolCallChip";

interface Props {
  apiKey: string;
}

interface Turn {
  role: "user" | "assistant";
  text: string;
}

export const AgentChat: React.FC<Props> = ({ apiKey }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState<Turn[]>([]);
  const [sessions, setSessions] = useState<AgentSessionSummary[]>([]);
  const [showMemory, setShowMemory] = useState(false);

  const { state, startChat, resume, reset } = useAgentStream();

  const refreshSessions = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/agent/sessions`, {
        headers: { "X-API-Key": apiKey },
      });
      if (resp.ok) {
        setSessions((await resp.json()) as AgentSessionSummary[]);
      }
    } catch {
      // ignore — session listing is best-effort
    }
  }, [apiKey]);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionId) {
      return sessionId;
    }
    try {
      const resp = await fetch(`${API_BASE_URL}/api/agent/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({ title: "" }),
      });
      if (!resp.ok) {
        return null;
      }
      const body = (await resp.json()) as CreateSessionResponse;
      setSessionId(body.session_id);
      return body.session_id;
    } catch {
      return null;
    }
  }, [apiKey, sessionId]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text) {
      return;
    }
    const sid = await ensureSession();
    if (!sid) {
      return;
    }
    setHistory((h) => [...h, { role: "user", text }]);
    setDraft("");
    reset();
    await startChat(sid, text, apiKey);
  }, [draft, ensureSession, apiKey, startChat, reset]);

  // When the stream finishes, snapshot the assistant text into history
  // so the next turn starts from a clean stream state.
  useEffect(() => {
    if (state.done && state.assistantText) {
      setHistory((h) => [
        ...h,
        { role: "assistant", text: state.assistantText },
      ]);
      reset();
      void refreshSessions();
    }
  }, [state.done, state.assistantText, reset, refreshSessions]);

  const toolChips = useMemo(
    () => Object.values(state.toolCalls),
    [state.toolCalls]
  );

  const handleApprove = useCallback(async () => {
    if (sessionId) {
      await resume(sessionId, "approve", apiKey);
    }
  }, [sessionId, resume, apiKey]);

  const handleReject = useCallback(async () => {
    if (sessionId) {
      await resume(sessionId, "reject", apiKey);
    }
  }, [sessionId, resume, apiKey]);

  return (
    <div
      data-testid="agent-chat"
      style={{ display: "flex", height: "100vh", fontFamily: "system-ui" }}
    >
      {/* Left: message thread */}
      <div
        style={{
          flex: "0 0 50%",
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid #e5e7eb",
        }}
      >
        <div
          style={{
            padding: "8px 16px",
            borderBottom: "1px solid #e5e7eb",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <strong>Agent</strong>
          <span style={{ color: "#6b7280", fontSize: 12 }}>
            {sessions.length} session{sessions.length === 1 ? "" : "s"}
          </span>
          <button
            onClick={() => setShowMemory((s) => !s)}
            data-testid="memory-toggle"
            style={{ marginLeft: "auto" }}
          >
            {showMemory ? "Hide memories" : "What I remember"}
          </button>
        </div>

        <div
          style={{ flex: 1, overflowY: "auto", padding: 16 }}
          data-testid="message-thread"
        >
          {history.map((t, i) => (
            <div
              key={i}
              style={{
                marginBottom: 12,
                color: t.role === "user" ? "#111827" : "#1f2937",
              }}
            >
              <strong>{t.role === "user" ? "You" : "Agent"}:</strong>{" "}
              {t.text}
            </div>
          ))}
          {state.isStreaming && (
            <div data-testid="streaming-row">
              {toolChips.map((tc) => (
                <ToolCallChip key={tc.call_id} state={tc} />
              ))}
              {state.assistantText && (
                <div style={{ color: "#1f2937" }}>
                  <strong>Agent:</strong> {state.assistantText}
                </div>
              )}
            </div>
          )}
          {state.error && (
            <div data-testid="stream-error" style={{ color: "#dc2626" }}>
              Error: {state.error}
            </div>
          )}
        </div>

        <div
          style={{
            padding: 12,
            borderTop: "1px solid #e5e7eb",
            display: "flex",
            gap: 8,
          }}
        >
          <input
            data-testid="composer-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={
              state.isStreaming
                ? "Streaming reply…"
                : "Ask the agent…"
            }
            disabled={state.isStreaming}
            style={{ flex: 1, padding: 8 }}
          />
          <button
            onClick={() => void send()}
            disabled={state.isStreaming || !draft.trim()}
            data-testid="composer-send"
          >
            Send
          </button>
        </div>
      </div>

      {/* Right: artifact panel + memory inspector */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        {showMemory ? (
          <MemoryInspector apiKey={apiKey} />
        ) : (
          <ArtifactPanelRouter panels={state.artifactPanels} />
        )}
      </div>

      {state.pendingInterrupt && (
        <InterruptDialog
          payload={state.pendingInterrupt}
          onApprove={() => void handleApprove()}
          onReject={() => void handleReject()}
        />
      )}
    </div>
  );
};
