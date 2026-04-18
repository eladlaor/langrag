/**
 * CitationCard - Expandable citation reference card
 *
 * Renders source-type-specific formatting:
 * - Podcast: shows timestamps
 * - Newsletter: shows date range and section title
 */

import React, { useState } from "react";
import { Card, Badge, Collapse } from "react-bootstrap";
import { RAGCitation } from "../../types/rag";

interface CitationCardProps {
  citation: RAGCitation;
}

const NEWSLETTER_SOURCE_TYPE = "newsletter";

export const CitationCard: React.FC<CitationCardProps> = ({ citation }) => {
  const [expanded, setExpanded] = useState(false);

  const metadata = citation.metadata || {};
  const isNewsletter = citation.source_type === NEWSLETTER_SOURCE_TYPE;

  // Podcast metadata
  const timestampStart = metadata.timestamp_start as number | undefined;
  const timestampEnd = metadata.timestamp_end as number | undefined;

  // Newsletter metadata
  const sectionTitle = metadata.section_title as string | undefined;
  const dateRange = metadata.newsletter_date_range as string | undefined;
  const sectionType = metadata.section_type as string | undefined;

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const formatSectionType = (type: string): string => {
    return type
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  };

  return (
    <Card
      className="mb-2 citation-card"
      style={{ fontSize: "0.85rem", cursor: "pointer" }}
      onClick={() => setExpanded(!expanded)}
    >
      <Card.Body className="p-2">
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <Badge bg="secondary">[{citation.index}]</Badge>
          <Badge bg={isNewsletter ? "success" : "info"}>
            {citation.source_type}
          </Badge>
          <strong>{citation.source_title}</strong>
          {/* Podcast: show timestamps */}
          {!isNewsletter && timestampStart !== undefined && (
            <Badge bg="outline-dark" text="dark" className="border">
              {formatTime(timestampStart)}
              {timestampEnd !== undefined && ` - ${formatTime(timestampEnd)}`}
            </Badge>
          )}
          {/* Newsletter: show date range and section */}
          {isNewsletter && dateRange && (
            <Badge bg="outline-dark" text="dark" className="border">
              {dateRange}
            </Badge>
          )}
          {isNewsletter && sectionType && (
            <Badge bg="warning" text="dark">
              {formatSectionType(sectionType)}
            </Badge>
          )}
          <Badge bg="light" text="dark" className="ms-auto">
            {(citation.search_score * 100).toFixed(0)}% match
          </Badge>
        </div>
        {/* Newsletter: show section title in expanded area */}
        <Collapse in={expanded}>
          <div className="mt-2 text-muted" style={{ fontSize: "0.8rem" }}>
            {isNewsletter && sectionTitle && (
              <div className="mb-1">
                <strong>Section:</strong> {sectionTitle}
              </div>
            )}
            {citation.snippet}
          </div>
        </Collapse>
      </Card.Body>
    </Card>
  );
};
