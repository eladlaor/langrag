/**
 * LoginGate - wraps the whole App and gates it behind the shared password.
 *
 *   status === 'checking'        -> centered spinner while the session probe runs
 *   status === 'authenticated'   -> render {children} (the real App)
 *   status === 'unauthenticated' -> render the styled login card only
 *
 * This is UX only; the real security boundary is the server-side
 * require_session dependency on every data router.
 */

import React, { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Container,
  Form,
  Spinner,
} from "react-bootstrap";
import { useAuth } from "../contexts/AuthContext";
import { LOGIN_BRANDING_TITLE } from "../constants";
import { logger } from "../utils/logger";

const LOG_COMPONENT = "LoginGate";

const fullViewportCenter: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

export const LoginGate: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { status, login } = useAuth();
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(false);
    setSubmitting(true);
    logger.info("Login form submitted", {
      component: LOG_COMPONENT,
      event: "login_submit",
    });
    try {
      await login(email, password);
      // On success the provider flips status to 'authenticated' and this
      // component re-renders into {children}.
    } catch (err) {
      logger.warn("Login form error", {
        component: LOG_COMPONENT,
        event: "login_submit",
        error: err instanceof Error ? err.message : "Unknown error",
      });
      setError(true);
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  };

  if (status === "checking") {
    return (
      <Container fluid style={fullViewportCenter}>
        <Spinner animation="border" variant="primary" role="status">
          <span className="visually-hidden">Checking session…</span>
        </Spinner>
      </Container>
    );
  }

  if (status === "authenticated") {
    return <>{children}</>;
  }

  // status === 'unauthenticated'
  return (
    <Container fluid style={fullViewportCenter} className="bg-light">
      <Card
        className="shadow-sm rounded"
        style={{ maxWidth: "400px", width: "100%" }}
      >
        <div
          className="bg-primary text-white text-center py-4 rounded-top"
        >
          <h1 className="h4 mb-0">{LOGIN_BRANDING_TITLE}</h1>
        </div>
        <Card.Body className="p-4">
          <p className="text-muted text-center mb-4">
            Sign in to your account
          </p>

          {error && (
            <Alert variant="danger" className="py-2">
              Incorrect email or password
            </Alert>
          )}

          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-3" controlId="loginEmail">
              <Form.Label className="visually-hidden">Email</Form.Label>
              <Form.Control
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
                autoComplete="username"
                disabled={submitting}
                isInvalid={error}
              />
            </Form.Group>

            <Form.Group className="mb-3" controlId="loginPassword">
              <Form.Label className="visually-hidden">Password</Form.Label>
              <Form.Control
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                disabled={submitting}
                isInvalid={error}
              />
            </Form.Group>

            <Button
              type="submit"
              variant="primary"
              className="w-100"
              disabled={
                submitting || email.length === 0 || password.length === 0
              }
            >
              {submitting ? (
                <>
                  <Spinner
                    as="span"
                    animation="border"
                    size="sm"
                    role="status"
                    aria-hidden="true"
                    className="me-2"
                  />
                  Signing in…
                </>
              ) : (
                "Sign In"
              )}
            </Button>
          </Form>
        </Card.Body>
      </Card>
    </Container>
  );
};
