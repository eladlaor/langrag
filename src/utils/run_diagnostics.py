"""
Run-scoped diagnostics aggregation for warnings and non-fatal errors.

Collects issues throughout the workflow for end-of-run reporting.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class DiagnosticSeverity(StrEnum):
    """Severity levels for diagnostic issues."""

    CRITICAL = "critical"  # Should have failed but was caught
    WARNING = "warning"  # Potential issue, workflow continued
    INFO = "info"  # Informational (e.g., fallback used)


@dataclass
class DiagnosticIssue:
    """A single diagnostic issue captured during the run."""

    severity: DiagnosticSeverity
    category: str  # e.g., "langfuse", "link_enrichment", "llm_confidence"
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    node_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class RunDiagnostics:
    """
    Aggregates diagnostic issues for a single run.

    Thread-safe collection of warnings and non-fatal errors.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.issues: list[DiagnosticIssue] = []
        self._lock = threading.Lock()

    def add_issue(self, severity: DiagnosticSeverity, category: str, message: str, node_name: str | None = None, details: dict[str, Any] | None = None) -> None:
        """Add a diagnostic issue to the collection."""
        issue = DiagnosticIssue(severity=severity, category=category, message=message, node_name=node_name, details=details or {})
        with self._lock:
            self.issues.append(issue)
        logger.debug(f"Diagnostic captured: [{severity}] {category}: {message}")

    def warning(self, category: str, message: str, **kwargs) -> None:
        """Convenience method for adding warnings."""
        self.add_issue(DiagnosticSeverity.WARNING, category, message, **kwargs)

    def info(self, category: str, message: str, **kwargs) -> None:
        """Convenience method for adding info issues."""
        self.add_issue(DiagnosticSeverity.INFO, category, message, **kwargs)

    def error(self, category: str, message: str, **kwargs) -> None:
        """Convenience method for adding critical/error issues."""
        self.add_issue(DiagnosticSeverity.CRITICAL, category, message, **kwargs)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all issues by severity."""
        return {"run_id": self.run_id, "total_issues": len(self.issues), "by_severity": {str(s): len([i for i in self.issues if i.severity == s]) for s in DiagnosticSeverity}, "issues": [{"severity": str(i.severity), "category": i.category, "message": i.message, "node": i.node_name, "timestamp": i.timestamp.isoformat(), "details": i.details} for i in sorted(self.issues, key=lambda x: (list(DiagnosticSeverity).index(x.severity), x.timestamp))]}


# Global registry of active diagnostics by run_id
_diagnostics_registry: dict[str, RunDiagnostics] = {}
_registry_lock = threading.Lock()


def get_diagnostics(run_id: str) -> RunDiagnostics:
    """Get or create diagnostics collector for a run."""
    with _registry_lock:
        if run_id not in _diagnostics_registry:
            _diagnostics_registry[run_id] = RunDiagnostics(run_id)
        return _diagnostics_registry[run_id]


def clear_diagnostics(run_id: str) -> None:
    """Clear diagnostics for a completed run."""
    with _registry_lock:
        _diagnostics_registry.pop(run_id, None)


