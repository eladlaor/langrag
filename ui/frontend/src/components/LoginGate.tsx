/**
 * LoginGate - wraps the whole App and gates it behind per-user login.
 *
 *   status === 'checking'        -> centered spinner while the session probe runs
 *   status === 'authenticated'   -> render {children} (the real App)
 *   status === 'unauthenticated' -> render the styled login card only
 *
 * This is UX only; the real security boundary is the server-side
 * require_session dependency on every data router.
 *
 * Palette: green/teal, reusing the docs pipeline-animation brand colors
 * (GREEN #10b981, TEAL #06b6d4) over a dark slate backdrop, so the entry
 * screen matches the project's visual identity rather than stock Bootstrap blue.
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

// Brand palette (mirrors docs/figures/pipeline-animation COLORS).
const BRAND = {
  GREEN: "#10b981",
  GREEN_DARK: "#0d9668",
  TEAL: "#06b6d4",
  BG_TOP: "#0f172a",
  BG_BOTTOM: "#0a0a1a",
} as const;

const fullViewportCenter: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: `radial-gradient(1200px 600px at 50% -10%, #13283a 0%, ${BRAND.BG_TOP} 45%, ${BRAND.BG_BOTTOM} 100%)`,
  padding: "1.5rem",
};

const cardStyle: React.CSSProperties = {
  maxWidth: "420px",
  width: "100%",
  border: "1px solid rgba(16, 185, 129, 0.15)",
  borderRadius: "16px",
  overflow: "hidden",
  boxShadow:
    "0 20px 60px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(6, 182, 212, 0.08), 0 0 40px rgba(16, 185, 129, 0.12)",
  backgroundColor: "#ffffff",
};

const headerStyle: React.CSSProperties = {
  background: `linear-gradient(135deg, ${BRAND.GREEN} 0%, ${BRAND.TEAL} 100%)`,
  color: "#ffffff",
  padding: "2rem 1.5rem",
  textAlign: "center",
};

const submitButtonStyle: React.CSSProperties = {
  background: `linear-gradient(135deg, ${BRAND.GREEN} 0%, ${BRAND.GREEN_DARK} 100%)`,
  border: "none",
  fontWeight: 600,
  letterSpacing: "0.02em",
  boxShadow: "0 6px 16px rgba(16, 185, 129, 0.35)",
};

// Inline styles cannot express :focus / :hover; inject a tiny scoped stylesheet
// once so the green focus ring and button hover-lift apply to this card only.
const SCOPED_STYLE_ID = "login-gate-brand-style";
const scopedCss = `
  .login-gate-card .form-control:focus {
    border-color: ${BRAND.GREEN};
    box-shadow: 0 0 0 0.2rem rgba(16, 185, 129, 0.25);
  }
  .login-gate-card .login-submit-btn:hover:not(:disabled),
  .login-gate-card .login-submit-btn:focus-visible:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 10px 22px rgba(16, 185, 129, 0.45);
    filter: brightness(1.03);
  }
  .login-gate-card .login-submit-btn {
    transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
  }
  .login-gate-card .login-submit-btn:disabled {
    opacity: 0.65;
  }
`;

const useScopedBrandStyle = (): void => {
  React.useEffect(() => {
    if (document.getElementById(SCOPED_STYLE_ID)) {
      return;
    }
    const styleEl = document.createElement("style");
    styleEl.id = SCOPED_STYLE_ID;
    styleEl.textContent = scopedCss;
    document.head.appendChild(styleEl);
  }, []);
};

export const LoginGate: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { status, login } = useAuth();
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);

  useScopedBrandStyle();

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
        <Spinner
          animation="border"
          role="status"
          style={{ color: BRAND.GREEN }}
        >
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
    <Container fluid style={fullViewportCenter}>
      <Card className="login-gate-card" style={cardStyle}>
        <div style={headerStyle}>
          <h1 className="h4 mb-0 fw-semibold">{LOGIN_BRANDING_TITLE}</h1>
        </div>
        <Card.Body className="p-4 p-sm-5">
          <p className="text-muted text-center mb-4">Sign in to your account</p>

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

            <Form.Group className="mb-4" controlId="loginPassword">
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
              className="w-100 login-submit-btn"
              style={submitButtonStyle}
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
