/**
 * RunsBrowser Component
 *
 * Browse past newsletter generation runs and view their content.
 * Features:
 * - List all runs with filters
 * - View newsletter content (HTML)
 * - One-click copy preserving format
 * - RTL/LTR toggle
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Card,
  Table,
  Button,
  Alert,
  Spinner,
  Badge,
  Form,
  ButtonGroup,
  OverlayTrigger,
  Tooltip,
} from "react-bootstrap";
import { api } from "../services/api";
import { RunInfo, NewsletterContentResponse } from "../types";
import { DiagnosticReport as DiagnosticReportModal } from "./DiagnosticReport";
import { DownloadDropdown } from "./DownloadDropdown";

interface RunsBrowserProps {
  onClose?: () => void;
}

export const RunsBrowser: React.FC<RunsBrowserProps> = ({ onClose }) => {
  // State for runs list
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<"all" | "periodic" | "daily">("all");
  const [filterSource, setFilterSource] = useState<string>("");

  // State for multi-select
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set());

  // State for newsletter viewer
  const [selectedRun, setSelectedRun] = useState<RunInfo | null>(null);
  const [newsletterContent, setNewsletterContent] = useState<NewsletterContentResponse | null>(null);
  const [loadingNewsletter, setLoadingNewsletter] = useState(false);
  // Persist direction preference in localStorage
  const [direction, setDirection] = useState<"rtl" | "ltr">(() => {
    const saved = localStorage.getItem('newsletter_direction');
    return (saved === 'ltr' || saved === 'rtl') ? saved : 'rtl';
  });
  const [copySuccess, setCopySuccess] = useState(false);

  // Save direction preference to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('newsletter_direction', direction);
  }, [direction]);

  // State for diagnostic viewer
  const [diagnosticRunId, setDiagnosticRunId] = useState<string | null>(null);

  // State for delete confirmation (supports single and bulk)
  const [deleteConfirmRunId, setDeleteConfirmRunId] = useState<string | null>(null);
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteProgress, setDeleteProgress] = useState<{ done: number; total: number } | null>(null);

  // Ref for the newsletter content container
  const contentRef = useRef<HTMLDivElement>(null);

  // Loading runs on mount and when filters change
  useEffect(() => {
    loadRuns();
  }, [filterType, filterSource]);

  const loadRuns = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { run_type?: "periodic" | "daily"; data_source?: string } = {};
      if (filterType !== "all") {
        params.run_type = filterType;
      }
      if (filterSource) {
        params.data_source = filterSource;
      }
      const response = await api.listRuns(params);
      setRuns(response.runs);
      setSelectedRunIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  };

  const loadNewsletter = async (run: RunInfo) => {
    setSelectedRun(run);
    setLoadingNewsletter(true);
    setNewsletterContent(null);
    try {
      const response = await api.getNewsletterContent(run.run_id, {
        run_type: run.run_type,
        format: "html",
      });
      setNewsletterContent(response);
      setDirection(response.direction);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load newsletter");
    } finally {
      setLoadingNewsletter(false);
    }
  };

  /**
   * Copying newsletter HTML to clipboard preserving formatting.
   * Using the Clipboard API with HTML MIME type for rich text support.
   */
  const copyToClipboard = useCallback(async () => {
    if (!newsletterContent?.content_html) return;

    // Parse the full HTML document so we can cleanly extract body and plain text
    // without regex pitfalls (HTML entities, <style>/<script> content, nested tags).
    const doc = new DOMParser().parseFromString(newsletterContent.content_html, "text/html");
    // Drop non-visible content so plain-text fallback doesn't leak CSS/JS
    doc.querySelectorAll("style, script, head").forEach((el) => el.remove());

    const bodyHtml = doc.body ? doc.body.innerHTML : newsletterContent.content_html;
    const plainText = (doc.body ? doc.body.innerText || doc.body.textContent || "" : "").trim();

    try {
      const clipboardItem = new ClipboardItem({
        "text/html": new Blob([bodyHtml], { type: "text/html" }),
        "text/plain": new Blob([plainText], { type: "text/plain" }),
      });

      await navigator.clipboard.write([clipboardItem]);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      // Fallback to plain text if rich HTML clipboard write is unsupported
      try {
        await navigator.clipboard.writeText(plainText);
        setCopySuccess(true);
        setTimeout(() => setCopySuccess(false), 2000);
      } catch (fallbackErr) {
        console.error("Failed to copy:", fallbackErr);
        setError("Failed to copy to clipboard");
      }
    }
  }, [newsletterContent]);

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "-";
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  const getStatusBadge = (run: RunInfo) => {
    if (run.has_hitl_pending) {
      return <Badge bg="warning">HITL Pending</Badge>;
    }
    // Ready if newsletter paths exist (either consolidated or per-chat)
    if (Object.keys(run.newsletter_paths).length > 0) {
      return <Badge bg="success">Ready</Badge>;
    }
    if (run.has_consolidated) {
      return <Badge bg="info">Consolidated</Badge>;
    }
    return <Badge bg="secondary">In Progress</Badge>;
  };

  const deleteRun = async (run: RunInfo) => {
    setIsDeleting(true);
    try {
      await api.deleteRun(run.run_id, run.run_type);
      setError(null);
      setDeleteConfirmRunId(null);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete run");
    } finally {
      setIsDeleting(false);
    }
  };

  const deleteBulkRuns = async () => {
    const runsToDelete = runs.filter((r) => selectedRunIds.has(r.run_id));
    if (runsToDelete.length === 0) return;

    setIsDeleting(true);
    setDeleteProgress({ done: 0, total: runsToDelete.length });
    const errors: string[] = [];

    for (let i = 0; i < runsToDelete.length; i++) {
      try {
        await api.deleteRun(runsToDelete[i].run_id, runsToDelete[i].run_type);
      } catch (err) {
        errors.push(`${runsToDelete[i].run_id}: ${err instanceof Error ? err.message : "Unknown error"}`);
      }
      setDeleteProgress({ done: i + 1, total: runsToDelete.length });
    }

    setBulkDeleteConfirm(false);
    setSelectedRunIds(new Set());
    setDeleteProgress(null);
    setIsDeleting(false);

    if (errors.length > 0) {
      setError(`Failed to delete ${errors.length} run(s): ${errors.join("; ")}`);
    }
    await loadRuns();
  };

  const toggleRunSelection = (runId: string) => {
    setSelectedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedRunIds.size === runs.length) {
      setSelectedRunIds(new Set());
    } else {
      setSelectedRunIds(new Set(runs.map((r) => r.run_id)));
    }
  };

  // Getting unique data sources for filter
  const dataSources = Array.from(new Set(runs.map((r) => r.data_source))).filter(Boolean);

  return (
    <Card className="mb-4">
      <Card.Header className="d-flex justify-content-between align-items-center">
        <strong>Past Runs Browser</strong>
        {onClose && (
          <Button variant="outline-secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        )}
      </Card.Header>
      <Card.Body>
        {error && (
          <Alert variant="danger" dismissible onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Filters */}
        <div className="d-flex gap-3 mb-3">
          <Form.Select
            size="sm"
            style={{ width: "150px" }}
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as "all" | "periodic" | "daily")}
          >
            <option value="all">All Types</option>
            <option value="periodic">Periodic</option>
            <option value="daily">Daily</option>
          </Form.Select>

          <Form.Select
            size="sm"
            style={{ width: "150px" }}
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
          >
            <option value="">All Sources</option>
            {dataSources.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </Form.Select>

          <Button variant="outline-primary" size="sm" onClick={loadRuns} disabled={loading}>
            {loading ? <Spinner animation="border" size="sm" /> : "Refresh"}
          </Button>
        </div>

        {/* Bulk Actions Bar */}
        {!selectedRun && selectedRunIds.size > 0 && (
          <div className="d-flex align-items-center gap-2 mb-3 p-2 bg-light rounded border">
            <span className="fw-bold">{selectedRunIds.size} run{selectedRunIds.size > 1 ? "s" : ""} selected</span>
            <Button
              variant="danger"
              size="sm"
              onClick={() => setBulkDeleteConfirm(true)}
              disabled={isDeleting}
            >
              Delete Selected
            </Button>
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={() => setSelectedRunIds(new Set())}
            >
              Clear Selection
            </Button>
          </div>
        )}

        {/* Runs Table */}
        {!selectedRun && (
          <div style={{ maxHeight: "400px", overflowY: "auto" }}>
            <Table striped bordered hover size="sm">
              <thead style={{ position: "sticky", top: 0, background: "white" }}>
                <tr>
                  <th style={{ width: "40px" }}>
                    <Form.Check
                      type="checkbox"
                      checked={runs.length > 0 && selectedRunIds.size === runs.length}
                      ref={(el: HTMLInputElement | null) => {
                        if (el) {
                          el.indeterminate = selectedRunIds.size > 0 && selectedRunIds.size < runs.length;
                        }
                      }}
                      onChange={toggleSelectAll}
                      title="Select all"
                    />
                  </th>
                  <th>Data Source</th>
                  <th>Date Range</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && !loading && (
                  <tr>
                    <td colSpan={7} className="text-center text-muted">
                      No runs found
                    </td>
                  </tr>
                )}
                {runs.map((run) => (
                  <tr key={run.run_id} className={selectedRunIds.has(run.run_id) ? "table-active" : ""}>
                    <td>
                      <Form.Check
                        type="checkbox"
                        checked={selectedRunIds.has(run.run_id)}
                        onChange={() => toggleRunSelection(run.run_id)}
                      />
                    </td>
                    <td>{run.data_source}</td>
                    <td>
                      {run.start_date} to {run.end_date}
                    </td>
                    <td>
                      <Badge bg={run.run_type === "periodic" ? "primary" : "secondary"}>
                        {run.run_type}
                      </Badge>
                    </td>
                    <td>{getStatusBadge(run)}</td>
                    <td>{formatDate(run.created_at)}</td>
                    <td>
                      <ButtonGroup size="sm">
                        <Button
                          variant="outline-primary"
                          onClick={() => loadNewsletter(run)}
                          disabled={Object.keys(run.newsletter_paths).length === 0}
                        >
                          View
                        </Button>
                        <Button
                          variant="outline-info"
                          onClick={() => setDiagnosticRunId(run.run_id)}
                        >
                          🔍 Diagnostics
                        </Button>
                        <DownloadDropdown
                          runId={run.run_id}
                          runType={run.run_type}
                          dataSource={run.data_source}
                          startDate={run.start_date}
                          endDate={run.end_date}
                          disabled={Object.keys(run.newsletter_paths).length === 0}
                          size="sm"
                        />
                        <Button
                          variant="outline-danger"
                          onClick={() => setDeleteConfirmRunId(run.run_id)}
                          disabled={isDeleting}
                        >
                          🗑️ Delete
                        </Button>
                      </ButtonGroup>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}

        {/* Newsletter Viewer */}
        {selectedRun && (
          <div>
            {/* Viewer Header */}
            <div className="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom">
              <div>
                <Button variant="link" className="p-0 me-2" onClick={() => setSelectedRun(null)}>
                  &larr; Back to list
                </Button>
                <span className="text-muted">
                  {selectedRun.data_source} | {selectedRun.start_date} to {selectedRun.end_date}
                </span>
              </div>

              <div className="d-flex gap-2">
                {/* RTL/LTR Toggle */}
                <ButtonGroup size="sm">
                  <OverlayTrigger
                    placement="top"
                    overlay={<Tooltip>Right-to-Left (Hebrew)</Tooltip>}
                  >
                    <Button
                      variant={direction === "rtl" ? "primary" : "outline-secondary"}
                      onClick={() => setDirection("rtl")}
                    >
                      RTL
                    </Button>
                  </OverlayTrigger>
                  <OverlayTrigger
                    placement="top"
                    overlay={<Tooltip>Left-to-Right (English)</Tooltip>}
                  >
                    <Button
                      variant={direction === "ltr" ? "primary" : "outline-secondary"}
                      onClick={() => setDirection("ltr")}
                    >
                      LTR
                    </Button>
                  </OverlayTrigger>
                </ButtonGroup>

                {/* Copy Button */}
                <OverlayTrigger
                  placement="top"
                  overlay={<Tooltip>Copy HTML to clipboard (preserves formatting for Substack)</Tooltip>}
                >
                  <Button
                    variant={copySuccess ? "success" : "outline-primary"}
                    size="sm"
                    onClick={copyToClipboard}
                    disabled={!newsletterContent?.content_html}
                  >
                    {copySuccess ? "Copied!" : "Copy for Substack"}
                  </Button>
                </OverlayTrigger>

                {/* Download Dropdown */}
                <DownloadDropdown
                  runId={selectedRun.run_id}
                  runType={selectedRun.run_type}
                  dataSource={selectedRun.data_source}
                  startDate={selectedRun.start_date}
                  endDate={selectedRun.end_date}
                  size="sm"
                />
              </div>
            </div>

            {/* Newsletter Content */}
            {loadingNewsletter ? (
              <div className="text-center py-5">
                <Spinner animation="border" />
                <p className="mt-2 text-muted">Loading newsletter...</p>
              </div>
            ) : newsletterContent?.content_html ? (
              <div
                ref={contentRef}
                dir={direction}
                style={{
                  border: "1px solid #dee2e6",
                  borderRadius: "4px",
                  padding: "20px",
                  maxHeight: "600px",
                  overflowY: "auto",
                  backgroundColor: "#fff",
                }}
                dangerouslySetInnerHTML={{
                  __html: extractBodyContent(newsletterContent.content_html),
                }}
              />
            ) : (
              <Alert variant="info">No newsletter content available for this run.</Alert>
            )}
          </div>
        )}
      </Card.Body>

      {/* Diagnostic Report Modal */}
      {diagnosticRunId && (
        <DiagnosticReportModal
          runId={diagnosticRunId}
          onClose={() => setDiagnosticRunId(null)}
        />
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirmRunId && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1050,
          }}
          onClick={() => setDeleteConfirmRunId(null)}
        >
          <Card
            style={{
              width: "400px",
              backgroundColor: "white",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <Card.Body>
              <Card.Title>Confirm Deletion</Card.Title>
              <p className="text-muted">
                Are you sure you want to delete this run and all its associated files? This action cannot be undone.
              </p>
              <p>
                <strong>Run ID:</strong> {deleteConfirmRunId}
              </p>
              <div className="d-flex gap-2 justify-content-end">
                <Button
                  variant="outline-secondary"
                  size="sm"
                  onClick={() => setDeleteConfirmRunId(null)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    const runToDelete = runs.find((r) => r.run_id === deleteConfirmRunId);
                    if (runToDelete) {
                      deleteRun(runToDelete);
                    }
                  }}
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <>
                      <Spinner animation="border" size="sm" className="me-2" />
                      Deleting...
                    </>
                  ) : (
                    "Delete"
                  )}
                </Button>
              </div>
            </Card.Body>
          </Card>
        </div>
      )}

      {/* Bulk Delete Confirmation Modal */}
      {bulkDeleteConfirm && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1050,
          }}
          onClick={() => !isDeleting && setBulkDeleteConfirm(false)}
        >
          <Card
            style={{
              width: "450px",
              backgroundColor: "white",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <Card.Body>
              <Card.Title>Confirm Bulk Deletion</Card.Title>
              <p className="text-muted">
                Are you sure you want to delete <strong>{selectedRunIds.size}</strong> run{selectedRunIds.size > 1 ? "s" : ""} and all their associated files? This action cannot be undone.
              </p>
              {deleteProgress && (
                <div className="mb-3">
                  <div className="d-flex justify-content-between mb-1">
                    <small>Deleting...</small>
                    <small>{deleteProgress.done} / {deleteProgress.total}</small>
                  </div>
                  <div className="progress">
                    <div
                      className="progress-bar"
                      role="progressbar"
                      style={{ width: `${(deleteProgress.done / deleteProgress.total) * 100}%` }}
                    />
                  </div>
                </div>
              )}
              <div className="d-flex gap-2 justify-content-end">
                <Button
                  variant="outline-secondary"
                  size="sm"
                  onClick={() => setBulkDeleteConfirm(false)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={deleteBulkRuns}
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <>
                      <Spinner animation="border" size="sm" className="me-2" />
                      Deleting...
                    </>
                  ) : (
                    `Delete ${selectedRunIds.size} Run${selectedRunIds.size > 1 ? "s" : ""}`
                  )}
                </Button>
              </div>
            </Card.Body>
          </Card>
        </div>
      )}
    </Card>
  );
};

/**
 * Extracting body content from full HTML document
 */
function extractBodyContent(html: string): string {
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  if (bodyMatch) {
    return bodyMatch[1];
  }
  // If no body tag, return as-is (might be fragment)
  return html;
}

export default RunsBrowser;
