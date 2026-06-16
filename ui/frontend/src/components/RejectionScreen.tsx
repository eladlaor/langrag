/**
 * RejectionScreen - shown when a self-signup attempt is rejected because the
 * email is not on the invite-only allowlist.
 *
 * Reached from two places:
 *   1. The signup form, when signup() throws NotAllowlistedError.
 *   2. App mount, when the Google OAuth callback redirected the SPA with
 *      `?signup=rejected&email=...` (AuthContext exposes the prefilled email).
 *
 * It explains the invite-only policy and offers a contact form that POSTs to
 * /api/auth/access-requests (name optional, email prefilled & editable,
 * message). The backend always returns a generic ack (anti-enumeration), so a
 * successful POST simply shows a confirmation regardless of duplicate state.
 *
 * Palette matches LoginGate (forest green) — same scoped card styling is
 * injected by the gate, so this renders inside the same card body.
 */

import React, { useState } from "react";
import { Alert, Button, Form, Spinner } from "react-bootstrap";
import {
  AUTH_ROUTES,
  FETCH_CREDENTIALS,
  HEADER_CONTENT_TYPE,
  CONTENT_TYPE_JSON,
} from "../constants";
import { logger } from "../utils/logger";

const LOG_COMPONENT = "RejectionScreen";

export interface RejectionScreenProps {
  /** Email to prefill in the contact form (from the failed signup attempt). */
  initialEmail?: string;
  /** Return to the sign-in / create-account view. */
  onBack: () => void;
  /** Brand green for the submit button, passed from the gate. */
  accentColor: string;
}

export const RejectionScreen: React.FC<RejectionScreenProps> = ({
  initialEmail = "",
  onBack,
  accentColor,
}) => {
  const [name, setName] = useState<string>("");
  const [email, setEmail] = useState<string>(initialEmail);
  const [message, setMessage] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitted, setSubmitted] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);

  React.useEffect(() => {
    logger.info("Component mounted", { component: LOG_COMPONENT });
    return () => {
      logger.info("Component unmounted", { component: LOG_COMPONENT });
    };
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(false);
    setSubmitting(true);
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "access_request",
      route: AUTH_ROUTES.ACCESS_REQUESTS,
      email,
    });
    try {
      const response = await fetch(AUTH_ROUTES.ACCESS_REQUESTS, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify({
          email: email.trim(),
          name: name.trim() || undefined,
          message: message.trim() || undefined,
        }),
      });
      if (!response.ok) {
        logger.warn("API call failure", {
          component: LOG_COMPONENT,
          event: "access_request",
          status: response.status,
        });
        throw new Error("access_request_failed");
      }
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "access_request",
        status: response.status,
      });
      setSubmitted(true);
    } catch (err) {
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "access_request",
        error: err instanceof Error ? err.message : "Unknown error",
      });
      setError(true);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div data-testid="rejection-screen-submitted">
        <Alert variant="success" className="py-3">
          Request received — an admin will review it.
        </Alert>
        <Button
          variant="link"
          className="w-100 p-0 mt-2"
          style={{ color: accentColor }}
          onClick={onBack}
        >
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <div data-testid="rejection-screen">
      <Alert variant="warning" className="py-3">
        Access to LangRAG is currently invite-only. Your email isn&apos;t on the
        approved list. Request access below and an admin will review it.
      </Alert>

      {error && (
        <Alert variant="danger" className="py-2">
          Something went wrong sending your request. Please try again.
        </Alert>
      )}

      <Form onSubmit={handleSubmit}>
        <Form.Group className="mb-3" controlId="accessRequestName">
          <Form.Label className="visually-hidden">Name</Form.Label>
          <Form.Control
            type="text"
            placeholder="Name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            disabled={submitting}
            data-testid="access-request-name"
          />
        </Form.Group>

        <Form.Group className="mb-3" controlId="accessRequestEmail">
          <Form.Label className="visually-hidden">Email</Form.Label>
          <Form.Control
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
            disabled={submitting}
            data-testid="access-request-email"
          />
        </Form.Group>

        <Form.Group className="mb-4" controlId="accessRequestMessage">
          <Form.Label className="visually-hidden">Message</Form.Label>
          <Form.Control
            as="textarea"
            rows={3}
            placeholder="Message (optional) — tell us a bit about yourself"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={submitting}
            data-testid="access-request-message"
          />
        </Form.Group>

        <Button
          type="submit"
          className="w-100 login-submit-btn"
          style={{
            background: accentColor,
            border: "none",
            fontWeight: 600,
            padding: "0.6rem",
          }}
          disabled={submitting || email.trim().length === 0}
          data-testid="access-request-submit"
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
              Sending…
            </>
          ) : (
            "Request access"
          )}
        </Button>

        <Button
          variant="link"
          className="w-100 p-0 mt-3"
          style={{ color: accentColor }}
          onClick={onBack}
          disabled={submitting}
          data-testid="rejection-back"
        >
          Back to sign in
        </Button>
      </Form>
    </div>
  );
};
