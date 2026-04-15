/**
 * CitationCard - Expandable citation reference card
 */

import React, { useState } from "react";
import { Card, Badge, Collapse } from "react-bootstrap";
import { RAGCitation } from "../../types/rag";

interface CitationCardProps {
  citation: RAGCitation;
}

export const CitationCard: React.FC<CitationCardProps> = ({ citation }) => {
  const [expanded, setExpanded] = useState(false);

  const metadata = citation.metadata || {};
  const timestampStart = metadata.timestamp_start as number | undefined;
  const timestampEnd = metadata.timestamp_end as number | undefined;

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <Card
      className="mb-2 citation-card"
      style={{ fontSize: "0.85rem", cursor: "pointer" }}
      onClick={() => setExpanded(!expanded)}
    >
      <Card.Body className="p-2">
        <div className="d-flex align-items-center gap-2">
          <Badge bg="secondary">[{citation.index}]</Badge>
          <Badge bg="info">{citation.source_type}</Badge>
          <strong>{citation.source_title}</strong>
          {timestampStart !== undefined && (
            <Badge bg="outline-dark" text="dark" className="border">
              {formatTime(timestampStart)}
              {timestampEnd !== undefined && ` - ${formatTime(timestampEnd)}`}
            </Badge>
          )}
          <Badge bg="light" text="dark" className="ms-auto">
            {(citation.search_score * 100).toFixed(0)}% match
          </Badge>
        </div>
        <Collapse in={expanded}>
          <div className="mt-2 text-muted" style={{ fontSize: "0.8rem" }}>
            {citation.snippet}
          </div>
        </Collapse>
      </Card.Body>
    </Card>
  );
};
