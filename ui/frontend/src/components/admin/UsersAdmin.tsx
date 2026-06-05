/**
 * UsersAdmin - admin-only account management view.
 *
 * Lists every account, supports creating users, toggling disabled state,
 * admin-resetting passwords, and deleting accounts. Renders an access note
 * for non-admins. All destructive actions use an inline confirm state rather
 * than blocking window.confirm/alert.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Spinner,
  Table,
} from "react-bootstrap";
import { useAuth } from "../../contexts/AuthContext";
import {
  api,
  AdminUser,
  CreateUserPayload,
  ApiError,
} from "../../services/api";
import {
  ROLE_ADMIN,
  ROLE_VIEWER,
  ERROR_DUPLICATE_EMAIL,
} from "../../constants";
import { logger } from "../../utils/logger";

const LOG_COMPONENT = "UsersAdmin";

const DUPLICATE_EMAIL_MESSAGE = "An account with that email already exists";

function parseCommunities(raw: string): string[] {
  return raw
    .split(",")
    .map((c) => c.trim())
    .filter((c) => c.length > 0);
}

export const UsersAdmin: React.FC = () => {
  const { isAdmin } = useAuth();

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [listError, setListError] = useState<string | null>(null);

  // Create-user form state.
  const [newEmail, setNewEmail] = useState<string>("");
  const [newPassword, setNewPassword] = useState<string>("");
  const [newRole, setNewRole] = useState<string>(ROLE_VIEWER);
  const [newCommunities, setNewCommunities] = useState<string>("");
  const [creating, setCreating] = useState<boolean>(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Per-row transient UI state.
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [resetForId, setResetForId] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState<string>("");
  const [rowBusyId, setRowBusyId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "list_users",
    });
    try {
      const result = await api.listUsers();
      setUsers(result);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "list_users",
        count: result.length,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error";
      setListError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "list_users",
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

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    const payload: CreateUserPayload = {
      email: newEmail.trim(),
      password: newPassword,
      role: newRole,
      communities: parseCommunities(newCommunities),
    };
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "create_user",
      email: payload.email,
      role: payload.role,
    });
    try {
      const created = await api.createUser(payload);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "create_user",
        user_id: created.user_id,
      });
      setNewEmail("");
      setNewPassword("");
      setNewRole(ROLE_VIEWER);
      setNewCommunities("");
      await refreshList();
    } catch (error) {
      const isDuplicate =
        error instanceof ApiError &&
        (error.status === 409 || error.message === ERROR_DUPLICATE_EMAIL);
      const message = isDuplicate
        ? DUPLICATE_EMAIL_MESSAGE
        : error instanceof Error
        ? error.message
        : "Unknown error";
      setCreateError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "create_user",
        email: payload.email,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setCreating(false);
    }
  };

  const handleToggleDisabled = async (user: AdminUser) => {
    setRowBusyId(user.user_id);
    setRowError(null);
    const next = !user.disabled;
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "set_user_disabled",
      user_id: user.user_id,
      disabled: next,
    });
    try {
      await api.setUserDisabled(user.user_id, next);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "set_user_disabled",
        user_id: user.user_id,
      });
      await refreshList();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error";
      setRowError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "set_user_disabled",
        user_id: user.user_id,
        error: message,
      });
    } finally {
      setRowBusyId(null);
    }
  };

  const handleResetPassword = async (userId: string) => {
    if (resetPassword.length === 0) return;
    setRowBusyId(userId);
    setRowError(null);
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "reset_password",
      user_id: userId,
    });
    try {
      await api.resetUserPassword(userId, resetPassword);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "reset_password",
        user_id: userId,
      });
      setResetForId(null);
      setResetPassword("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error";
      setRowError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "reset_password",
        user_id: userId,
        error: message,
      });
    } finally {
      setRowBusyId(null);
    }
  };

  const handleDelete = async (userId: string) => {
    setRowBusyId(userId);
    setRowError(null);
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "delete_user",
      user_id: userId,
    });
    try {
      await api.deleteUser(userId);
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "delete_user",
        user_id: userId,
      });
      setPendingDeleteId(null);
      await refreshList();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error";
      setRowError(message);
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "delete_user",
        user_id: userId,
        error: message,
      });
    } finally {
      setRowBusyId(null);
    }
  };

  if (!isAdmin) {
    return (
      <Alert variant="warning" data-testid="users-admin-access-note">
        You do not have permission to manage user accounts. This view is
        restricted to administrators.
      </Alert>
    );
  }

  return (
    <div data-testid="users-admin">
      <Card className="mb-4">
        <Card.Header>Create user</Card.Header>
        <Card.Body>
          {createError && (
            <Alert variant="danger" data-testid="create-user-error">
              {createError}
            </Alert>
          )}
          <Form onSubmit={handleCreate}>
            <div className="row g-3">
              <Form.Group className="col-md-4" controlId="newUserEmail">
                <Form.Label>Email</Form.Label>
                <Form.Control
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  autoComplete="off"
                  required
                  disabled={creating}
                />
              </Form.Group>
              <Form.Group className="col-md-3" controlId="newUserPassword">
                <Form.Label>Password</Form.Label>
                <Form.Control
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                  disabled={creating}
                />
              </Form.Group>
              <Form.Group className="col-md-2" controlId="newUserRole">
                <Form.Label>Role</Form.Label>
                <Form.Select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  disabled={creating}
                >
                  <option value={ROLE_VIEWER}>viewer</option>
                  <option value={ROLE_ADMIN}>admin</option>
                </Form.Select>
              </Form.Group>
              <Form.Group className="col-md-3" controlId="newUserCommunities">
                <Form.Label>Communities</Form.Label>
                <Form.Control
                  type="text"
                  placeholder="comma,separated"
                  value={newCommunities}
                  onChange={(e) => setNewCommunities(e.target.value)}
                  disabled={creating}
                />
              </Form.Group>
            </div>
            <Button
              type="submit"
              variant="primary"
              className="mt-3"
              disabled={
                creating ||
                newEmail.trim().length === 0 ||
                newPassword.length === 0
              }
            >
              {creating ? "Creating…" : "Create user"}
            </Button>
          </Form>
        </Card.Body>
      </Card>

      {rowError && (
        <Alert variant="danger" data-testid="users-admin-row-error">
          {rowError}
        </Alert>
      )}
      {listError && (
        <Alert variant="danger" data-testid="users-admin-list-error">
          {listError}
        </Alert>
      )}

      {loading ? (
        <div className="text-center py-4">
          <Spinner animation="border" role="status">
            <span className="visually-hidden">Loading users…</span>
          </Spinner>
        </div>
      ) : (
        <Table striped bordered hover responsive data-testid="users-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Communities</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const busy = rowBusyId === user.user_id;
              return (
                <tr key={user.user_id} data-testid={`user-row-${user.user_id}`}>
                  <td>{user.email}</td>
                  <td>
                    <Badge
                      bg={user.role === ROLE_ADMIN ? "primary" : "secondary"}
                    >
                      {user.role}
                    </Badge>
                  </td>
                  <td>
                    {user.communities.length > 0
                      ? user.communities.join(", ")
                      : "—"}
                  </td>
                  <td>
                    {user.disabled ? (
                      <Badge bg="danger">disabled</Badge>
                    ) : (
                      <Badge bg="success">active</Badge>
                    )}
                  </td>
                  <td>
                    <div className="d-flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant={
                          user.disabled ? "outline-success" : "outline-warning"
                        }
                        disabled={busy}
                        onClick={() => void handleToggleDisabled(user)}
                        data-testid={`toggle-disabled-${user.user_id}`}
                      >
                        {user.disabled ? "Enable" : "Disable"}
                      </Button>

                      <Button
                        size="sm"
                        variant="outline-secondary"
                        disabled={busy}
                        onClick={() => {
                          setResetForId(
                            resetForId === user.user_id ? null : user.user_id
                          );
                          setResetPassword("");
                        }}
                        data-testid={`reset-password-${user.user_id}`}
                      >
                        Reset password
                      </Button>

                      {pendingDeleteId === user.user_id ? (
                        <>
                          <Button
                            size="sm"
                            variant="danger"
                            disabled={busy}
                            onClick={() => void handleDelete(user.user_id)}
                            data-testid={`confirm-delete-${user.user_id}`}
                          >
                            Confirm delete
                          </Button>
                          <Button
                            size="sm"
                            variant="outline-secondary"
                            disabled={busy}
                            onClick={() => setPendingDeleteId(null)}
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline-danger"
                          disabled={busy}
                          onClick={() => setPendingDeleteId(user.user_id)}
                          data-testid={`delete-${user.user_id}`}
                        >
                          Delete
                        </Button>
                      )}
                    </div>

                    {resetForId === user.user_id && (
                      <Form
                        className="mt-2 d-flex gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void handleResetPassword(user.user_id);
                        }}
                      >
                        <Form.Control
                          type="password"
                          size="sm"
                          placeholder="New password"
                          value={resetPassword}
                          onChange={(e) => setResetPassword(e.target.value)}
                          autoComplete="new-password"
                          disabled={busy}
                          data-testid={`reset-password-input-${user.user_id}`}
                        />
                        <Button
                          size="sm"
                          type="submit"
                          variant="primary"
                          disabled={busy || resetPassword.length === 0}
                          data-testid={`reset-password-submit-${user.user_id}`}
                        >
                          Save
                        </Button>
                      </Form>
                    )}
                  </td>
                </tr>
              );
            })}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="text-center text-muted">
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      )}
    </div>
  );
};
