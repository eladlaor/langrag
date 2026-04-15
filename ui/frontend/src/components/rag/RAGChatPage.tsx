/**
 * RAGChatPage - Main chat page for RAG knowledge conversations
 *
 * Layout: SourceSelector (top) -> ChatMessageList (center) -> ChatInput (bottom)
 */

import React, { useState, useCallback, useEffect } from "react";
import { Card, Alert } from "react-bootstrap";
import { RAGMessage } from "../../types/rag";
import { useRAGChat } from "../../hooks/useRAGChat";
import { SourceSelector } from "./SourceSelector";
import { ChatMessageList } from "./ChatMessageList";
import { ChatInput } from "./ChatInput";

export const RAGChatPage: React.FC = () => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [contentSources, setContentSources] = useState<string[]>(["podcast"]);
  const [messages, setMessages] = useState<RAGMessage[]>([]);

  const { state, sendMessage, reset } = useRAGChat();

  // Capture session_id from the backend once it's assigned
  useEffect(() => {
    if (state.sessionId && state.sessionId !== sessionId) {
      setSessionId(state.sessionId);
    }
  }, [state.sessionId, sessionId]);

  const handleSend = useCallback(
    (query: string) => {
      // Add user message to local state
      const userMessage: RAGMessage = {
        message_id: `temp-${Date.now()}`,
        role: "user",
        content: query,
      };
      setMessages((prev) => [...prev, userMessage]);

      // Send to backend (uses sessionId if we have one from a previous exchange)
      sendMessage({
        session_id: sessionId,
        query,
        content_sources: contentSources,
      });
    },
    [sessionId, contentSources, sendMessage]
  );

  // When streaming completes, add the assistant message to local state
  useEffect(() => {
    if (
      state.status === "idle" &&
      state.currentAnswer &&
      messages.length > 0 &&
      messages[messages.length - 1].role === "user"
    ) {
      const assistantMessage: RAGMessage = {
        message_id: `assistant-${Date.now()}`,
        role: "assistant",
        content: state.currentAnswer,
        citations: state.citations,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      reset();
    }
  }, [state.status, state.currentAnswer, state.citations, messages, reset]);

  const handleNewChat = () => {
    setSessionId(null);
    setMessages([]);
    reset();
  };

  return (
    <div className="d-flex flex-column" style={{ height: "calc(100vh - 250px)" }}>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <SourceSelector selected={contentSources} onChange={setContentSources} />
        <button
          className="btn btn-outline-secondary btn-sm"
          onClick={handleNewChat}
        >
          New Chat
        </button>
      </div>

      <Card className="flex-grow-1 d-flex flex-column">
        <ChatMessageList
          messages={messages}
          streamingContent={state.currentAnswer}
          streamingCitations={state.citations}
          isStreaming={state.status === "streaming"}
        />

        {state.error && (
          <Alert variant="danger" className="mx-3 mb-2" dismissible>
            {state.error}
          </Alert>
        )}

        <div className="p-3 border-top">
          <ChatInput
            onSend={handleSend}
            disabled={state.status === "streaming"}
          />
        </div>
      </Card>
    </div>
  );
};
