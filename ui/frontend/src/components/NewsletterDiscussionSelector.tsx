/**
 * Newsletter Discussion Selector Component
 *
 * Phase 2 HITL component for selecting discussions after Phase 1 ranking.
 * Displays ranked discussions in a table with checkboxes and generates
 * the final newsletter using selected discussions.
 */

import React, { useState, useEffect } from "react";
import { Table, Button, Form, Alert, Spinner, Badge, Collapse, OverlayTrigger, Tooltip } from "react-bootstrap";
import { api, ApiError } from "../services/api";
import {
  RankedDiscussionItem,
  DiscussionSelectionResponse,
  Phase2GenerationResponse,
} from "../types";

interface NewsletterDiscussionSelectorProps {
  runDirectory: string;
  onGenerationComplete?: (result: Phase2GenerationResponse) => void;
}

export const NewsletterDiscussionSelector: React.FC<NewsletterDiscussionSelectorProps> = ({
  runDirectory,
  onGenerationComplete,
}) => {
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [discussions, setDiscussions] = useState<RankedDiscussionItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [formatType, setFormatType] = useState<string>("");
  const [timeoutDeadline, setTimeoutDeadline] = useState<string>("");
  const [generating, setGenerating] = useState<boolean>(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [generationResult, setGenerationResult] = useState<Phase2GenerationResponse | null>(null);
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
  const [loadingHtml, setLoadingHtml] = useState<boolean>(false);
  const [showHtmlPreview, setShowHtmlPreview] = useState<boolean>(false);
  const [copySuccess, setCopySuccess] = useState<boolean>(false);

  // Loading discussions on mount
  useEffect(() => {
    loadDiscussions();
  }, [runDirectory]);

  // Fetching HTML content when generation completes
  useEffect(() => {
    if (generationResult && generationResult.enriched_html_path) {
      fetchHtmlContent(generationResult.enriched_html_path);
    }
  }, [generationResult]);

  const fetchHtmlContent = async (filePath: string) => {
    setLoadingHtml(true);
    try {
      const response = await api.getNewsletterFileContent(filePath);
      setHtmlContent(response.content);
    } catch (err) {
      console.error("Failed to fetch HTML content:", err);
    } finally {
      setLoadingHtml(false);
    }
  };

  const handleCopyHtml = async () => {
    if (!htmlContent) return;

    try {
      await navigator.clipboard.writeText(htmlContent);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 3000);
    } catch (err) {
      console.error("Failed to copy HTML:", err);
      alert("Failed to copy to clipboard");
    }
  };

  const loadDiscussions = async () => {
    setLoading(true);
    setError(null);

    try {
      const response: DiscussionSelectionResponse = await api.getDiscussionSelection(runDirectory);
      setDiscussions(response.discussions);
      setFormatType(response.format_type);
      setTimeoutDeadline(response.timeout_deadline);

      // Pre-selecting top 3-5 discussions by default
      const defaultSelections = response.discussions
        .slice(0, Math.min(5, response.discussions.length))
        .map((d) => d.id);
      setSelectedIds(new Set(defaultSelections));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load discussions: ${err.message}`);
      } else {
        setError("Failed to load discussions. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(discussions.map((d) => d.id)));
    } else {
      setSelectedIds(new Set());
    }
  };

  const handleSelectDiscussion = (id: string, checked: boolean) => {
    const newSelected = new Set(selectedIds);
    if (checked) {
      newSelected.add(id);
    } else {
      newSelected.delete(id);
    }
    setSelectedIds(newSelected);
  };

  const toggleRowExpansion = (id: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedRows(newExpanded);
  };

  const handleGenerateNewsletter = async () => {
    if (selectedIds.size === 0) {
      setError("Please select at least one discussion");
      return;
    }

    setGenerating(true);
    setError(null);
    setGenerationResult(null);

    try {
      // Step 1: Saving selections
      await api.saveDiscussionSelections({
        run_directory: runDirectory,
        selected_discussion_ids: Array.from(selectedIds),
      });

      // Step 2: Generating newsletter
      const result = await api.generateNewsletterPhase2({
        run_directory: runDirectory,
      });

      setGenerationResult(result);

      if (onGenerationComplete) {
        onGenerationComplete(result);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Generation failed: ${err.message}`);
      } else {
        setError("Failed to generate newsletter. Please try again.");
      }
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" role="status">
          <span className="visually-hidden">Loading discussions...</span>
        </Spinner>
        <p className="mt-3">Loading ranked discussions...</p>
      </div>
    );
  }

  if (error && discussions.length === 0) {
    return (
      <Alert variant="danger">
        <Alert.Heading>Error Loading Discussions</Alert.Heading>
        <p>{error}</p>
        <Button variant="outline-danger" onClick={loadDiscussions}>
          Retry
        </Button>
      </Alert>
    );
  }

  const allSelected = selectedIds.size === discussions.length && discussions.length > 0;
  const someSelected = selectedIds.size > 0 && selectedIds.size < discussions.length;

  return (
    <div className="newsletter-discussion-selector">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h4>Select Discussions for Newsletter</h4>
          <p className="text-muted mb-0">
            Format: <Badge bg="info">{formatType}</Badge> |
            Selected: <Badge bg="primary">{selectedIds.size}</Badge> of {discussions.length}
          </p>
          {timeoutDeadline && (
            <p className="text-muted small mb-0">
              Selection expires: {new Date(timeoutDeadline).toLocaleString()}
            </p>
          )}
        </div>
        <Button
          variant="success"
          size="lg"
          disabled={selectedIds.size === 0 || generating}
          onClick={handleGenerateNewsletter}
        >
          {generating ? (
            <>
              <Spinner
                as="span"
                animation="border"
                size="sm"
                role="status"
                aria-hidden="true"
                className="me-2"
              />
              Generating...
            </>
          ) : (
            `Generate Newsletter (${selectedIds.size} selected)`
          )}
        </Button>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {generationResult && (
        <>
          <Alert variant="success">
            <Alert.Heading>Newsletter Generated Successfully!</Alert.Heading>
            <p>
              <strong>Path:</strong> <code>{generationResult.newsletter_path}</code>
            </p>
            <p className="mb-0">
              <strong>Discussions:</strong> {generationResult.num_discussions} |{" "}
              <strong>Length:</strong> {generationResult.content_length} characters |{" "}
              <strong>Validation:</strong>{" "}
              {generationResult.validation_passed ? (
                <Badge bg="success">Passed</Badge>
              ) : (
                <Badge bg="danger">Failed</Badge>
              )}
            </p>
          </Alert>

          {/* HTML Preview Section */}
          {htmlContent && (
            <div className="card mb-3">
              <div className="card-header bg-primary text-white d-flex justify-content-between align-items-center">
                <h5 className="mb-0">Newsletter Preview</h5>
                <div>
                  <Button
                    variant="light"
                    size="sm"
                    onClick={handleCopyHtml}
                    className="me-2"
                  >
                    {copySuccess ? "Copied!" : "Copy HTML"}
                  </Button>
                  <Button
                    variant="light"
                    size="sm"
                    onClick={() => setShowHtmlPreview(!showHtmlPreview)}
                  >
                    {showHtmlPreview ? "Hide Preview" : "Show Preview"}
                  </Button>
                </div>
              </div>
              <Collapse in={showHtmlPreview}>
                <div>
                  <div className="card-body" style={{ maxHeight: "600px", overflowY: "auto" }}>
                    <div dangerouslySetInnerHTML={{ __html: htmlContent }} />
                  </div>
                </div>
              </Collapse>
            </div>
          )}

          {loadingHtml && (
            <div className="text-center py-3">
              <Spinner animation="border" size="sm" className="me-2" />
              <span>Loading newsletter preview...</span>
            </div>
          )}
        </>
      )}

      <div className="table-responsive" style={{ maxHeight: "600px", overflowY: "auto" }}>
        <Table striped bordered hover size="sm">
          <thead className="sticky-top bg-light">
            <tr>
              <th style={{ width: "50px" }}>
                <Form.Check
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => handleSelectAll(e.target.checked)}
                  ref={(input: any) => {
                    if (input) input.indeterminate = someSelected;
                  }}
                />
              </th>
              <th style={{ width: "60px" }}>Rank</th>
              <th style={{ minWidth: "200px" }}>Title</th>
              <th style={{ minWidth: "150px" }}>Group</th>
              <th style={{ width: "100px" }}>Date</th>
              <th style={{ width: "80px" }}>Time</th>
              <th style={{ width: "80px" }}>Messages</th>
              <th style={{ width: "100px" }}>Participants</th>
              <th style={{ width: "80px" }}>Score</th>
              <th style={{ width: "60px" }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {discussions.map((discussion) => (
              <React.Fragment key={discussion.id}>
                <tr
                  className={selectedIds.has(discussion.id) ? "table-primary" : ""}
                  style={{ cursor: "pointer" }}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <Form.Check
                      type="checkbox"
                      checked={selectedIds.has(discussion.id)}
                      onChange={(e) => handleSelectDiscussion(discussion.id, e.target.checked)}
                    />
                  </td>
                  <td className="text-center">
                    <Badge bg={discussion.rank <= 3 ? "success" : discussion.rank <= 5 ? "warning" : "secondary"}>
                      {discussion.rank}
                    </Badge>
                  </td>
                  <td>
                    <strong>{discussion.title}</strong>
                  </td>
                  <td className="text-muted small">
                    {discussion.is_merged && discussion.source_groups ? (
                      <div>
                        <Badge bg="info" className="me-1">Merged</Badge>
                        <OverlayTrigger
                          placement="top"
                          overlay={
                            <Tooltip id={`tooltip-groups-${discussion.id}`}>
                              <strong>Discussed in:</strong>
                              <ul className="list-unstyled mb-0 mt-1">
                                {discussion.source_groups.map((group, idx) => (
                                  <li key={idx}>• {group}</li>
                                ))}
                              </ul>
                            </Tooltip>
                          }
                        >
                          <span className="text-decoration-underline" style={{ cursor: "pointer" }}>
                            {discussion.source_groups.length} groups
                          </span>
                        </OverlayTrigger>
                      </div>
                    ) : (
                      discussion.group_name
                    )}
                  </td>
                  <td className="text-center small">
                    {discussion.is_merged && discussion.source_discussions ? (
                      <OverlayTrigger
                        placement="top"
                        overlay={
                          <Tooltip id={`tooltip-dates-${discussion.id}`}>
                            <strong>Discussion timeline:</strong>
                            <ul className="list-unstyled mb-0 mt-1">
                              {discussion.source_discussions.map((source, idx) => {
                                const dt = new Date(source.first_message_timestamp);
                                return (
                                  <li key={idx}>
                                    • {source.group}: {dt.toLocaleDateString('en-GB')}
                                  </li>
                                );
                              })}
                            </ul>
                          </Tooltip>
                        }
                      >
                        <span className="text-decoration-underline" style={{ cursor: "pointer" }}>
                          {discussion.first_message_date} *
                        </span>
                      </OverlayTrigger>
                    ) : (
                      discussion.first_message_date
                    )}
                  </td>
                  <td className="text-center small">
                    {discussion.is_merged ? (
                      <span className="text-muted">Various</span>
                    ) : (
                      discussion.first_message_time
                    )}
                  </td>
                  <td className="text-center">{discussion.num_messages}</td>
                  <td className="text-center">{discussion.num_unique_participants}</td>
                  <td className="text-center">
                    <Badge bg={
                      discussion.relevance_score && discussion.relevance_score >= 8
                        ? "success"
                        : discussion.relevance_score && discussion.relevance_score >= 6
                        ? "warning"
                        : "secondary"
                    }>
                      {discussion.relevance_score?.toFixed(1) || "N/A"}
                    </Badge>
                  </td>
                  <td className="text-center">
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => toggleRowExpansion(discussion.id)}
                    >
                      {expandedRows.has(discussion.id) ? "▲" : "▼"}
                    </Button>
                  </td>
                </tr>
                <tr>
                  <td colSpan={10} className="p-0">
                    <Collapse in={expandedRows.has(discussion.id)}>
                      <div className="p-3 bg-light">
                        <div className="mb-2">
                          <strong>Nutshell:</strong>
                          <p className="mb-0 text-muted">{discussion.nutshell}</p>
                        </div>
                        <div>
                          <strong>Reasoning:</strong>
                          <p className="mb-0 text-muted">{discussion.reasoning}</p>
                        </div>
                      </div>
                    </Collapse>
                  </td>
                </tr>
              </React.Fragment>
            ))}
          </tbody>
        </Table>
      </div>

      <div className="mt-3 d-flex justify-content-between align-items-center">
        <div>
          <Badge bg="secondary" className="me-2">Total: {discussions.length}</Badge>
          <Badge bg="primary" className="me-2">Selected: {selectedIds.size}</Badge>
        </div>
        <Button
          variant="success"
          disabled={selectedIds.size === 0 || generating}
          onClick={handleGenerateNewsletter}
        >
          {generating ? "Generating..." : `Generate Newsletter (${selectedIds.size} selected)`}
        </Button>
      </div>
    </div>
  );
};
