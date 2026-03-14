/**
 * DiagnosticReport Component
 *
 * Displays diagnostic issues captured during newsletter generation.
 * Shows LLM-generated analysis, prioritized issues, and recommendations.
 */

import React, { useEffect, useState } from "react";
import { DiagnosticReport as DiagnosticReportType, DiagnosticIssue } from "../types";
import { api } from "../services/api";

interface DiagnosticReportProps {
  runId: string;
  onClose: () => void;
}

export const DiagnosticReport: React.FC<DiagnosticReportProps> = ({ runId, onClose }) => {
  const [report, setReport] = useState<DiagnosticReportType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDiagnostics = async () => {
      try {
        const diagnostics = await api.getRunDiagnostics(runId);
        setReport(diagnostics);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load diagnostics");
      } finally {
        setLoading(false);
      }
    };

    fetchDiagnostics();
  }, [runId]);

  if (loading) {
    return (
      <div className="diagnostic-modal-overlay">
        <div className="diagnostic-modal">
          <div className="diagnostic-header">
            <h2>Loading Diagnostics...</h2>
            <button onClick={onClose} className="close-button">×</button>
          </div>
          <div className="diagnostic-loading">
            <div className="spinner"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="diagnostic-modal-overlay">
        <div className="diagnostic-modal">
          <div className="diagnostic-header">
            <h2>Error Loading Diagnostics</h2>
            <button onClick={onClose} className="close-button">×</button>
          </div>
          <div className="diagnostic-error">
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!report || report.status === "clean") {
    return (
      <div className="diagnostic-modal-overlay">
        <div className="diagnostic-modal">
          <div className="diagnostic-header">
            <h2>Diagnostic Report</h2>
            <button onClick={onClose} className="close-button">×</button>
          </div>
          <div className="diagnostic-clean">
            <div className="status-icon">✅</div>
            <h3>No Issues Detected</h3>
            <p>Newsletter generation completed without warnings or errors.</p>
          </div>
        </div>
      </div>
    );
  }

  const { by_severity, report: analysis, raw_issues } = report;

  return (
    <div className="diagnostic-modal-overlay" onClick={onClose}>
      <div className="diagnostic-modal" onClick={(e) => e.stopPropagation()}>
        <div className="diagnostic-header">
          <h2>Diagnostic Report</h2>
          <button onClick={onClose} className="close-button">×</button>
        </div>

        {/* Severity Summary */}
        <div className="diagnostic-summary">
          <div className="severity-badges">
            {by_severity && (
              <>
                {by_severity.critical > 0 && (
                  <span className="severity-badge critical">
                    🔴 {by_severity.critical} Critical
                  </span>
                )}
                {by_severity.warning > 0 && (
                  <span className="severity-badge warning">
                    🟡 {by_severity.warning} Warnings
                  </span>
                )}
                {by_severity.info > 0 && (
                  <span className="severity-badge info">
                    🔵 {by_severity.info} Info
                  </span>
                )}
              </>
            )}
          </div>
          {analysis?.executive_summary && (
            <p className="executive-summary">{analysis.executive_summary}</p>
          )}
        </div>

        {/* Issues List */}
        {analysis?.issues_by_priority && analysis.issues_by_priority.length > 0 && (
          <div className="diagnostic-section">
            <h3>Issues (by priority)</h3>
            <div className="issues-list">
              {analysis.issues_by_priority.map((issue, idx) => (
                <div key={idx} className={`issue-item ${issue.severity}`}>
                  <div className="issue-header">
                    <span className={`severity-indicator ${issue.severity}`}>
                      {issue.severity === "critical" ? "🔴" : issue.severity === "warning" ? "🟡" : "🔵"}
                    </span>
                    <span className="issue-category">[{issue.category}]</span>
                    {issue.node && <span className="issue-node">in {issue.node}</span>}
                  </div>
                  <div className="issue-message">{issue.message}</div>
                  {issue.details && Object.keys(issue.details).length > 0 && (
                    <details className="issue-details">
                      <summary>Details</summary>
                      <pre>{JSON.stringify(issue.details, null, 2)}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recommendations */}
        {analysis?.actionable_recommendations && analysis.actionable_recommendations.length > 0 && (
          <div className="diagnostic-section">
            <h3>💡 Recommendations</h3>
            <ul className="recommendations-list">
              {analysis.actionable_recommendations.map((rec, idx) => (
                <li key={idx}>{rec}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Patterns Detected */}
        {analysis?.patterns_detected && analysis.patterns_detected.length > 0 && (
          <div className="diagnostic-section">
            <h3>🔍 Patterns Detected</h3>
            <ul className="patterns-list">
              {analysis.patterns_detected.map((pattern, idx) => (
                <li key={idx}>{pattern}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};
