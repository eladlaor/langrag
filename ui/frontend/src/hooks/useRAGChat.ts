/**
 * React hook for RAG chat SSE streaming
 *
 * Manages an EventSource connection to /api/rag/chat/stream,
 * accumulates tokens, handles citation/done/error events.
 */

import { useState, useCallback, useRef } from "react";
import { RAGChatState, RAGCitation, RAGChatRequest } from "../types/rag";
import { API_BASE_URL } from "../constants";
import { RAG_API_ROUTES, RAG_SSE_EVENTS } from "../constants/rag";

const INITIAL_STATE: RAGChatState = {
  status: "idle",
  currentAnswer: "",
  citations: [],
  error: null,
  sessionId: null,
};

interface UseRAGChatReturn {
  state: RAGChatState;
  sendMessage: (request: RAGChatRequest) => void;
  reset: () => void;
}

export function useRAGChat(): UseRAGChatReturn {
  const [state, setState] = useState<RAGChatState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback((request: RAGChatRequest) => {
    // Cancel any existing stream
    if (abortRef.current) {
      abortRef.current.abort();
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setState({
      status: "streaming",
      currentAnswer: "",
      citations: [],
      error: null,
      sessionId: null,
    });

    const url = `${API_BASE_URL}${RAG_API_ROUTES.CHAT_STREAM}`;

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse SSE events from buffer
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer

          let currentEvent = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith("data: ") && currentEvent) {
              const data = line.slice(6);
              try {
                const parsed = JSON.parse(data);
                handleSSEEvent(currentEvent, parsed, setState);
              } catch {
                // Ignore malformed JSON
              }
              currentEvent = "";
            }
          }
        }

        // Finalize
        setState((prev) => ({
          ...prev,
          status: prev.status === "streaming" ? "idle" : prev.status,
        }));
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setState((prev) => ({
          ...prev,
          status: "error",
          error: err.message,
        }));
      });
  }, []);

  const reset = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setState(INITIAL_STATE);
  }, []);

  return { state, sendMessage, reset };
}

function handleSSEEvent(
  eventType: string,
  data: Record<string, unknown>,
  setState: React.Dispatch<React.SetStateAction<RAGChatState>>
): void {
  switch (eventType) {
    case RAG_SSE_EVENTS.TOKEN:
      setState((prev) => ({
        ...prev,
        currentAnswer: prev.currentAnswer + (data.token as string),
      }));
      break;

    case RAG_SSE_EVENTS.CITATION:
      setState((prev) => ({
        ...prev,
        citations: [...prev.citations, data as unknown as RAGCitation],
      }));
      break;

    case RAG_SSE_EVENTS.DONE:
      setState((prev) => ({
        ...prev,
        status: "idle",
        sessionId: (data.session_id as string) || prev.sessionId,
      }));
      break;

    case RAG_SSE_EVENTS.ERROR:
      setState((prev) => ({
        ...prev,
        status: "error",
        error: data.error as string,
      }));
      break;
  }
}
