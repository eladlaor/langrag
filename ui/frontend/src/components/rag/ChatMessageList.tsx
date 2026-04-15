/**
 * ChatMessageList - Scrollable message display with citations
 */

import React, { useRef, useEffect } from "react";
import { RAGMessage, RAGCitation } from "../../types/rag";
import { CitationCard } from "./CitationCard";

interface ChatMessageListProps {
  messages: RAGMessage[];
  streamingContent: string;
  streamingCitations: RAGCitation[];
  isStreaming: boolean;
}

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  streamingContent,
  streamingCitations,
  isStreaming,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  return (
    <div
      className="flex-grow-1 overflow-auto p-3"
      style={{ minHeight: "300px", maxHeight: "60vh" }}
    >
      {messages.length === 0 && !isStreaming && (
        <div className="text-center text-muted py-5">
          <h5>Knowledge Chat</h5>
          <p>Ask questions about ingested podcasts and other content sources.</p>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.message_id} message={msg} />
      ))}

      {isStreaming && streamingContent && (
        <div className="mb-3">
          <div className="d-flex">
            <div
              className="p-3 rounded bg-light"
              style={{ maxWidth: "80%", whiteSpace: "pre-wrap" }}
            >
              {streamingContent}
              <span className="blinking-cursor">|</span>
            </div>
          </div>
        </div>
      )}

      {!isStreaming && streamingCitations.length > 0 && (
        <div className="mb-3 ms-2">
          <small className="text-muted d-block mb-1">Sources:</small>
          {streamingCitations.map((c) => (
            <CitationCard key={c.chunk_id} citation={c} />
          ))}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
};

const MessageBubble: React.FC<{ message: RAGMessage }> = ({ message }) => {
  const isUser = message.role === "user";

  return (
    <div className={`mb-3 d-flex ${isUser ? "justify-content-end" : ""}`}>
      <div
        className={`p-3 rounded ${isUser ? "bg-primary text-white" : "bg-light"}`}
        style={{ maxWidth: "80%", whiteSpace: "pre-wrap" }}
      >
        {message.content}
      </div>
      {!isUser && message.citations && message.citations.length > 0 && (
        <div className="ms-2 mt-2">
          {message.citations.map((c) => (
            <CitationCard key={c.chunk_id} citation={c} />
          ))}
        </div>
      )}
    </div>
  );
};
