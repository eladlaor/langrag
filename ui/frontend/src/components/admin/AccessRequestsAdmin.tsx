/**
 * AccessRequestsAdmin - admin-only review of self-signup access requests.
 *
 * Lists GET /api/auth/access-requests?status=pending (newest first, served by
 * the backend). Read-only: the backend exposes no approve/reject action yet, so
 * this surfaces who has asked for access and lets an admin provision them via
 * the existing Users tab. Renders an access note for non-admins.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Alert, Card, Spinner, Table } from "react-bootstrap";
import { useAuth } from "../../contexts/AuthContext";
import { api } from "../../services/api";
import { AccessRequest } from "../../types";
import { ACCESS_REQUEST_STATUS_PENDING } from "../../constants";
import { logger } from "../../utils/logger";

const LOG_COMPONENT = "AccessRequestsAdmin";

function formatTimestamp(raw?: string | null): string {
  if (!raw) return "—";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString();
}

export const AccessRequestsAdmin: React.FC = () => {
  const { isAdmin } = useAuth();

  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [listError, setListError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "list_access_requests",
      status: ACCESS_REQUEST_STATUS_PENDING,
    });
    try {
      const result = await api.listAccessRequests(ACCESS_REQUEST_STATUS_PENDING);
      setRequests(result);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "list_access_requests",
        count: result.length,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setListError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "list_access_requests",
        error: message,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    logger.info("Component mounted", { component: LOG_COMPONENT, isAdmin });
    if (isAdmin) {
      void refreshList();
    } else {
      setLoading(false);
    }
    return () => {
      logger.info("Component unmounted", { component: LOG_COMPONENT });
    };
  }, [isAdmin, refreshList]);

  if (!isAdmin) {
    return (
      <Alert variant="warning" data-testid="access-requests-access-note">
        You do not have permission to view access requests. This view is
        restricted to administrators.
      </Alert>
    );
  }

  return (
    <div data-testid="access-requests-admin">
      <Card className="mb-4">
        <Card.Header>Pending access requests</Card.Header>
        <Card.Body>
          <p className="text-muted mb-0" style={{ fontSize: "0.9rem" }}>
            People who requested access but are not yet on the allowlist. To
            grant access, create their account in the Users tab.
          </p>
        </Card.Body>
      </Card>

      {listError && (
        <Alert variant="danger" data-testid="access-requests-list-error">
          {listError}
        </Alert>
      )}

      {loading ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading access requests…</span>
          </Spinner>
        </div>
      ) : (
        <Table striped bordered hover responsive data-testid="access-requests-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Name</th>
              <th>Message</th>
              <th>Requested</th>
            </tr>
          </thead>
          <tbody>
            {requests.map((request) => (
              <tr
                key={request.request_id}
                data-testid={`access-request-row-${request.request_id}`}
              >
                <td>{request.email}</td>
                <td>{request.name && request.name.length > 0 ? request.name : "—"}</td>
                <td style={{ whiteSpace: "pre-wrap" }}>
                  {request.message && request.message.length > 0
                    ? request.message
                    : "—"}
                </td>
                <td>{formatTimestamp(request.created_at)}</td>
              </tr>
            ))}
            {requests.length === 0 && (
              <tr>
                <td colSpan={4} className="text-center text-muted">
                  No pending access requests.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      )}
    </div>
  );
};
