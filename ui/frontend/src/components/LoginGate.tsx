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
 * Palette: forest green, matching the app-wide design system (accent
 * #1f7a3d) over a deep forest backdrop, so the entry screen is the same
 * sharp, elegant identity carried through the rest of the product.
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
import { useAuth, NotAllowlistedError } from "../contexts/AuthContext";
import { LOGIN_BRANDING_TITLE } from "../constants";
import { logger } from "../utils/logger";
import { RejectionScreen } from "./RejectionScreen";

const LOG_COMPONENT = "LoginGate";

// In-card view modes for the unauthenticated gate.
type GateMode = "signin" | "signup" | "rejected";

// Brand palette — forest green, matching the app-wide design system.
const BRAND = {
  GREEN: "#1f7a3d",
  GREEN_DARK: "#155c2c",
  GREEN_DEEP: "#0e3a1c",
  BG_TOP: "#0d2e18",
  BG_BOTTOM: "#08200f",
} as const;

const fullViewportCenter: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: `radial-gradient(1100px 560px at 50% -8%, #164a27 0%, ${BRAND.BG_TOP} 48%, ${BRAND.BG_BOTTOM} 100%)`,
  padding: "1.5rem",
};

const cardStyle: React.CSSProperties = {
  maxWidth: "420px",
  width: "100%",
  border: "1px solid rgba(255, 255, 255, 0.08)",
  borderRadius: "18px",
  overflow: "hidden",
  boxShadow:
    "0 30px 70px -20px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(31, 122, 61, 0.12)",
  backgroundColor: "#ffffff",
};

const headerStyle: React.CSSProperties = {
  background: "#ffffff",
  color: "#11211a",
  padding: "2.25rem 1.5rem 1.5rem",
  textAlign: "center",
  borderBottom: "1px solid #e2e9dd",
  borderTop: `3px solid ${BRAND.GREEN}`,
};

const submitButtonStyle: React.CSSProperties = {
  background: BRAND.GREEN,
  border: "none",
  fontWeight: 600,
  letterSpacing: "0.01em",
  padding: "0.6rem",
  boxShadow: "0 6px 16px -6px rgba(31, 122, 61, 0.45)",
};

// Inline styles cannot express :focus / :hover; inject a tiny scoped stylesheet
// once so the green focus ring and button hover-lift apply to this card only.
const SCOPED_STYLE_ID = "login-gate-brand-style";
const scopedCss = `
  .login-gate-card .form-control:focus {
    border-color: ${BRAND.GREEN};
    box-shadow: 0 0 0 3.5px rgba(31, 122, 61, 0.18);
  }
  .login-gate-card .login-submit-btn:hover:not(:disabled),
  .login-gate-card .login-submit-btn:focus-visible:not(:disabled) {
    background: ${BRAND.GREEN_DARK} !important;
    transform: translateY(-1px);
    box-shadow: 0 10px 22px -8px rgba(31, 122, 61, 0.5);
  }
  .login-gate-card .login-submit-btn {
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
  }
  .login-gate-card .login-submit-btn:disabled {
    opacity: 0.6;
  }
  .login-gate-card .login-wordmark {
    font-family: "Fraunces", Georgia, serif;
    font-weight: 600;
    font-size: 1.9rem;
    letter-spacing: -0.025em;
    color: #11211a;
    font-optical-sizing: auto;
    margin: 0;
  }
  .login-gate-card .login-wordmark .accent { color: ${BRAND.GREEN}; }
  .login-gate-card .google-btn {
    background: #ffffff;
    color: #1f2933;
    border: 1px solid #d7dee3;
    font-weight: 600;
    padding: 0.6rem;
    transition: background 0.15s ease, box-shadow 0.15s ease;
  }
  .login-gate-card .google-btn:hover:not(:disabled),
  .login-gate-card .google-btn:focus-visible:not(:disabled) {
    background: #f4f6f8;
    box-shadow: 0 4px 12px -6px rgba(0, 0, 0, 0.25);
    color: #1f2933;
  }
  .login-gate-card .gate-divider {
    display: flex;
    align-items: center;
    color: #8a958c;
    font-size: 0.8rem;
    margin: 1.1rem 0;
  }
  .login-gate-card .gate-divider::before,
  .login-gate-card .gate-divider::after {
    content: "";
    flex: 1;
    height: 1px;
    background: #e2e9dd;
  }
  .login-gate-card .gate-divider span { padding: 0 0.75rem; }
  .login-gate-card .gate-toggle-link {
    color: ${BRAND.GREEN};
    background: none;
    border: none;
    font-weight: 600;
    padding: 0;
    text-decoration: none;
  }
  .login-gate-card .gate-toggle-link:hover { text-decoration: underline; }
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
  const { status, login, signup, loginWithGoogle, config, rejectedSignup } =
    useAuth();
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [confirmPassword, setConfirmPassword] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);
  // Generic signup failure (disabled / duplicate / validation), distinct from
  // the invite-only rejection which switches to the RejectionScreen.
  const [signupError, setSignupError] = useState<boolean>(false);
  const [confirmMismatch, setConfirmMismatch] = useState<boolean>(false);

  // A Google-redirect rejection (?signup=rejected) starts the gate in the
  // rejection view with the email prefilled.
  const [mode, setMode] = useState<GateMode>(
    rejectedSignup ? "rejected" : "signin"
  );
  const [rejectedEmail, setRejectedEmail] = useState<string>(
    rejectedSignup?.email ?? ""
  );

  useScopedBrandStyle();

  const resetTransient = () => {
    setError(false);
    setSignupError(false);
    setConfirmMismatch(false);
    setPassword("");
    setConfirmPassword("");
  };

  const switchMode = (next: GateMode) => {
    resetTransient();
    setMode(next);
    logger.info("Gate mode switched", {
      component: LOG_COMPONENT,
      event: "gate_mode_switch",
      mode: next,
    });
  };

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

  const handleSignupSubmit = async (
    event: React.FormEvent<HTMLFormElement>
  ) => {
    event.preventDefault();
    setSignupError(false);
    setConfirmMismatch(false);
    if (password !== confirmPassword) {
      setConfirmMismatch(true);
      logger.info("Signup form rejected — password mismatch", {
        component: LOG_COMPONENT,
        event: "signup_submit",
      });
      return;
    }
    setSubmitting(true);
    logger.info("Signup form submitted", {
      component: LOG_COMPONENT,
      event: "signup_submit",
    });
    try {
      await signup(email, password);
      // On success the provider flips status to 'authenticated'.
    } catch (err) {
      if (err instanceof NotAllowlistedError) {
        logger.info("Signup not allowlisted — showing rejection screen", {
          component: LOG_COMPONENT,
          event: "signup_submit",
        });
        setRejectedEmail(email);
        setPassword("");
        setConfirmPassword("");
        setMode("rejected");
        return;
      }
      logger.warn("Signup form error", {
        component: LOG_COMPONENT,
        event: "signup_submit",
        error: err instanceof Error ? err.message : "Unknown error",
      });
      setSignupError(true);
      setPassword("");
      setConfirmPassword("");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogle = () => {
    logger.info("Continue with Google clicked", {
      component: LOG_COMPONENT,
      event: "google_click",
    });
    loginWithGoogle();
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
          <h1 className="login-wordmark">
            {LOGIN_BRANDING_TITLE.replace(/RAG$/, "")}
            <span className="accent">RAG</span>
          </h1>
        </div>
        <Card.Body className="p-4 p-sm-5">
          {mode === "rejected" ? (
            <>
              <p
                className="text-muted text-center mb-4"
                style={{ fontSize: "0.9rem" }}
              >
                Request access to LangRAG
              </p>
              <RejectionScreen
                initialEmail={rejectedEmail}
                accentColor={BRAND.GREEN}
                onBack={() => switchMode("signin")}
              />
            </>
          ) : (
            <>
              <p
                className="text-muted text-center mb-4"
                style={{ fontSize: "0.9rem" }}
              >
                Newsletter intelligence —{" "}
                {mode === "signin" ? "sign in to continue" : "create your account"}
              </p>

              {config.googleEnabled && (
                <>
                  <Button
                    type="button"
                    className="w-100 google-btn"
                    onClick={handleGoogle}
                    disabled={submitting}
                    data-testid="google-login-btn"
                  >
                    Continue with Google
                  </Button>
                  <div className="gate-divider">
                    <span>or</span>
                  </div>
                </>
              )}

              {mode === "signin" ? (
                <>
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
                      <Form.Label className="visually-hidden">
                        Password
                      </Form.Label>
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
                        submitting ||
                        email.length === 0 ||
                        password.length === 0
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
                  {config.signupEnabled && (
                    <p
                      className="text-center text-muted mb-0 mt-4"
                      style={{ fontSize: "0.85rem" }}
                    >
                      Don&apos;t have an account?{" "}
                      <button
                        type="button"
                        className="gate-toggle-link"
                        onClick={() => switchMode("signup")}
                        data-testid="toggle-to-signup"
                      >
                        Create account
                      </button>
                    </p>
                  )}
                </>
              ) : (
                <>
                  {signupError && (
                    <Alert variant="danger" className="py-2">
                      Could not create your account. Please check your details
                      and try again.
                    </Alert>
                  )}
                  <Form onSubmit={handleSignupSubmit}>
                    <Form.Group className="mb-3" controlId="signupEmail">
                      <Form.Label className="visually-hidden">Email</Form.Label>
                      <Form.Control
                        type="email"
                        placeholder="Email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        autoFocus
                        autoComplete="username"
                        disabled={submitting}
                        isInvalid={signupError}
                        data-testid="signup-email"
                      />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="signupPassword">
                      <Form.Label className="visually-hidden">
                        Password
                      </Form.Label>
                      <Form.Control
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="new-password"
                        disabled={submitting}
                        isInvalid={signupError}
                        data-testid="signup-password"
                      />
                    </Form.Group>

                    <Form.Group className="mb-4" controlId="signupConfirm">
                      <Form.Label className="visually-hidden">
                        Confirm password
                      </Form.Label>
                      <Form.Control
                        type="password"
                        placeholder="Confirm password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        autoComplete="new-password"
                        disabled={submitting}
                        isInvalid={confirmMismatch}
                        data-testid="signup-confirm"
                      />
                      {confirmMismatch && (
                        <Form.Control.Feedback type="invalid">
                          Passwords do not match.
                        </Form.Control.Feedback>
                      )}
                    </Form.Group>

                    <Button
                      type="submit"
                      className="w-100 login-submit-btn"
                      style={submitButtonStyle}
                      disabled={
                        submitting ||
                        email.length === 0 ||
                        password.length === 0 ||
                        confirmPassword.length === 0
                      }
                      data-testid="signup-submit"
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
                          Creating account…
                        </>
                      ) : (
                        "Create account"
                      )}
                    </Button>
                  </Form>
                  <p
                    className="text-center text-muted mb-0 mt-4"
                    style={{ fontSize: "0.85rem" }}
                  >
                    Already have an account?{" "}
                    <button
                      type="button"
                      className="gate-toggle-link"
                      onClick={() => switchMode("signin")}
                      data-testid="toggle-to-signin"
                    >
                      Sign in
                    </button>
                  </p>
                </>
              )}
            </>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
};
