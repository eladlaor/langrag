/**
 * PodcastPortal — the standalone PUBLIC page at langrag.ai/podcasts.
 *
 * Rendered by index.tsx OUTSIDE the AuthProvider/LoginGate: it must be reachable
 * by strangers with no app account and must never surface app chrome or login.
 * See knowledge/plans/PODCAST_MCP_PUBLIC_ACCESS.md.
 *
 * Flow:
 *   - Default: hero + a name(optional)/email form → requestKey → "check your email".
 *   - With `?token=...` in the URL: auto-verify → show the API key ONCE with a
 *     copy button and a "save it now" warning.
 * Setup snippets (Claude Code / Cursor / generic SSE), the two MCP tools, and a
 * short FAQ are always shown so a visitor understands the product before signing up.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Form,
  Nav,
  Spinner,
} from "react-bootstrap";
import { z } from "zod";

import { logger } from "../../utils/logger";
import { podcastApi, PodcastApiError } from "../../services/podcastApi";
import {
  API_KEY_PLACEHOLDER,
  KEYLESS_SETUP_SNIPPETS,
  MCP_HTTP_URL,
  MCP_TOOLS,
  PODCAST_FAQ,
  PODCAST_LOG_COMPONENT,
  PODCAST_VERIFY_TOKEN_PARAM,
  SETUP_SNIPPETS,
} from "../../constants/podcast";

// ---- Brand palette (mirrors LoginGate so the public page shares identity) ----
const BRAND = {
  GREEN: "#1f7a3d",
  GREEN_DARK: "#155c2c",
  BG_TOP: "#0d2e18",
  BG_BOTTOM: "#08200f",
} as const;

const SCOPED_STYLE_ID = "podcast-portal-brand-style";
const scopedCss = `
  .podcast-portal { min-height: 100vh; background: #f6f8f5; color: #11211a; }
  .podcast-hero {
    background: radial-gradient(1100px 560px at 50% -18%, #164a27 0%, ${BRAND.BG_TOP} 55%, ${BRAND.BG_BOTTOM} 100%);
    color: #ffffff;
    padding: 4rem 1.5rem 3.5rem;
    text-align: center;
  }
  .podcast-hero h1 {
    font-family: "Fraunces", Georgia, serif;
    font-weight: 600;
    font-size: clamp(1.9rem, 4vw, 2.9rem);
    letter-spacing: -0.025em;
    margin: 0 0 0.75rem;
  }
  .podcast-hero .accent { color: #6fd08c; }
  .podcast-hero p { max-width: 720px; margin: 0 auto; opacity: 0.92; font-size: 1.05rem; }
  .podcast-portal .brand-btn {
    background: ${BRAND.GREEN}; border: none; font-weight: 600; padding: 0.6rem 1.2rem;
    transition: background 0.15s ease, transform 0.15s ease;
  }
  .podcast-portal .brand-btn:hover:not(:disabled),
  .podcast-portal .brand-btn:focus-visible:not(:disabled) {
    background: ${BRAND.GREEN_DARK}; transform: translateY(-1px);
  }
  .podcast-portal .form-control:focus {
    border-color: ${BRAND.GREEN}; box-shadow: 0 0 0 3.5px rgba(31,122,61,0.18);
  }
  .podcast-portal .snippet-block {
    background: #0e1f16; color: #d7f0de; border-radius: 10px; padding: 1rem 1.1rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85rem;
    white-space: pre; overflow-x: auto; margin: 0;
  }
  .podcast-portal .snippet-wrap { position: relative; }
  .podcast-portal .snippet-copy { position: absolute; top: 0.6rem; right: 0.6rem; }
  .podcast-portal .tool-sig {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem;
    color: ${BRAND.GREEN_DARK}; font-weight: 600;
  }
  .podcast-portal a { color: ${BRAND.GREEN_DARK}; }
`;

const useScopedBrandStyle = (): void => {
  useEffect(() => {
    if (document.getElementById(SCOPED_STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = SCOPED_STYLE_ID;
    el.textContent = scopedCss;
    document.head.appendChild(el);
  }, []);
};

// Email validation at the form boundary (the app uses Zod for validation).
const EmailSchema = z.string().trim().email();

// Read the verify token from the current URL (?token=...), if present.
const readVerifyToken = (): string | null => {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const token = params.get(PODCAST_VERIFY_TOKEN_PARAM);
  return token && token.trim().length > 0 ? token.trim() : null;
};

type VerifyStatus = "idle" | "verifying" | "success" | "error";

// A small copy-to-clipboard button with transient "Copied" feedback.
const CopyButton: React.FC<{ value: string; label: string; logEvent: string }> = ({
  value,
  label,
  logEvent,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      logger.info("podcast portal copy", {
        component: PODCAST_LOG_COMPONENT,
        event: logEvent,
      });
      window.setTimeout(() => setCopied(false), 1800);
    } catch (error) {
      logger.error("podcast portal copy failed", {
        component: PODCAST_LOG_COMPONENT,
        event: logEvent,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  }, [value, logEvent]);

  return (
    <Button
      variant="outline-light"
      size="sm"
      onClick={() => void handleCopy()}
      aria-label={`Copy ${label}`}
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
};

export const PodcastPortal: React.FC = () => {
  useScopedBrandStyle();

  // ---- Verify flow (auto-runs when a token is in the URL) ----
  const initialToken = useMemo(() => readVerifyToken(), []);
  const [verifyStatus, setVerifyStatus] = useState<VerifyStatus>(
    initialToken ? "verifying" : "idle"
  );
  const [apiKey, setApiKey] = useState<string | null>(null);
  // Endpoint returned by verify (result.mcp_url). Falls back to the constant when
  // absent so staging/prod can differ without a rebuild (F3).
  const [mcpUrl, setMcpUrl] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  // ---- Request-key form ----
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [requestSent, setRequestSent] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  // Mount / unmount structured logging.
  useEffect(() => {
    logger.info("podcast portal mounted", {
      component: PODCAST_LOG_COMPONENT,
      event: "mount",
      has_token: Boolean(initialToken),
    });
    return () => {
      logger.info("podcast portal unmounted", {
        component: PODCAST_LOG_COMPONENT,
        event: "unmount",
      });
    };
  }, [initialToken]);

  // Auto-verify once on load when a token is present.
  useEffect(() => {
    if (!initialToken) return;
    let cancelled = false;

    const run = async () => {
      logger.info("podcast key verify start", {
        component: PODCAST_LOG_COMPONENT,
        event: "verify_start",
      });
      try {
        const result = await podcastApi.verify(initialToken);
        if (cancelled) return;
        setApiKey(result.api_key);
        setMcpUrl(result.mcp_url || null);
        setVerifyStatus("success");
        logger.info("podcast key verify success", {
          component: PODCAST_LOG_COMPONENT,
          event: "verify_success",
        });
      } catch (error) {
        if (cancelled) return;
        const status = error instanceof PodcastApiError ? error.status : 0;
        const message =
          status === 410
            ? "This verification link has expired. Please request a new key."
            : status === 400
            ? "This verification link is invalid. Please request a new key."
            : "Could not verify your link. Please try again or request a new key.";
        setVerifyError(message);
        setVerifyStatus("error");
        logger.error("podcast key verify failed", {
          component: PODCAST_LOG_COMPONENT,
          event: "verify_failure",
          status,
          error: error instanceof Error ? error.message : "Unknown error",
        });
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [initialToken]);

  const handleRequest = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setRequestError(null);
      setEmailError(null);

      const parsed = EmailSchema.safeParse(email);
      if (!parsed.success) {
        setEmailError("Please enter a valid email address.");
        logger.warn("podcast key request rejected — invalid email", {
          component: PODCAST_LOG_COMPONENT,
          event: "request_validation_failed",
        });
        return;
      }

      setSubmitting(true);
      logger.info("podcast key request start", {
        component: PODCAST_LOG_COMPONENT,
        event: "request_start",
        has_name: name.trim().length > 0,
      });
      try {
        await podcastApi.requestKey(parsed.data, name);
        setRequestSent(true);
        logger.info("podcast key request success", {
          component: PODCAST_LOG_COMPONENT,
          event: "request_success",
        });
      } catch (error) {
        setRequestError(
          "Something went wrong sending your request. Please try again shortly."
        );
        logger.error("podcast key request failed", {
          component: PODCAST_LOG_COMPONENT,
          event: "request_failure",
          error: error instanceof Error ? error.message : "Unknown error",
        });
      } finally {
        setSubmitting(false);
      }
    },
    [email, name]
  );

  return (
    <div className="podcast-portal">
      <header className="podcast-hero">
        <h1>
          Query the LangTalks <span className="accent">podcast</span> from your agent
        </h1>
        <p>
          Query the LangTalks podcast (and future podcasts) from your own AI agent via
          MCP. Your agent&apos;s LLM writes the answers; we serve dated, cited transcript
          chunks. Works instantly with no API key — grab a free key below for higher
          daily limits.
        </p>
      </header>

      <Container style={{ maxWidth: 860 }} className="py-4 py-md-5 d-flex flex-column gap-4">
        {/* ---- Verify flow takes priority when a token is present ---- */}
        {initialToken && (
          <VerifyPanel
            status={verifyStatus}
            apiKey={apiKey}
            error={verifyError}
          />
        )}

        {/* ---- Keyless quick start: the zero-setup default path ---- */}
        <KeylessSection mcpUrl={mcpUrl} />

        {/* ---- Request-key form (hidden once a key has been shown) ---- */}
        {verifyStatus !== "success" && (
          <Card>
            <Card.Header>Get an API key (higher limits)</Card.Header>
            <Card.Body>
              {requestSent ? (
                <Alert variant="success" className="mb-0">
                  <div className="fw-bold mb-1">Check your email.</div>
                  If that address is eligible, we&apos;ve sent a verification link. Open it
                  to reveal your API key. The link expires, so use it soon.
                </Alert>
              ) : (
                <>
                  <p className="text-muted">
                    Enter your email to receive a verification link. Your key is shown once
                    after you verify.
                  </p>
                  {requestError && <Alert variant="danger">{requestError}</Alert>}
                  <Form onSubmit={handleRequest} noValidate>
                    <Form.Group className="mb-3" controlId="podcastName">
                      <Form.Label>Name (optional)</Form.Label>
                      <Form.Control
                        type="text"
                        placeholder="Ada Lovelace"
                        value={name}
                        maxLength={120}
                        disabled={submitting}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </Form.Group>
                    <Form.Group className="mb-3" controlId="podcastEmail">
                      <Form.Label>Email</Form.Label>
                      <Form.Control
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        disabled={submitting}
                        isInvalid={Boolean(emailError)}
                        onChange={(e) => setEmail(e.target.value)}
                        autoComplete="email"
                      />
                      {emailError && (
                        <Form.Control.Feedback type="invalid">
                          {emailError}
                        </Form.Control.Feedback>
                      )}
                    </Form.Group>
                    <Button
                      type="submit"
                      className="brand-btn"
                      disabled={submitting || email.trim().length === 0}
                    >
                      {submitting ? (
                        <>
                          <Spinner as="span" size="sm" animation="border" className="me-2" />
                          Sending…
                        </>
                      ) : (
                        "Send verification link"
                      )}
                    </Button>
                  </Form>
                </>
              )}
            </Card.Body>
          </Card>
        )}

        <SetupSection apiKey={apiKey} mcpUrl={mcpUrl} />
        <ToolsSection />
        <FaqSection />
      </Container>
    </div>
  );
};

// ---- Verify result panel -------------------------------------------------

const VerifyPanel: React.FC<{
  status: VerifyStatus;
  apiKey: string | null;
  error: string | null;
}> = ({ status, apiKey, error }) => {
  if (status === "verifying") {
    return (
      <Card>
        <Card.Body className="d-flex align-items-center gap-3">
          <Spinner animation="border" style={{ color: BRAND.GREEN }} />
          <span>Verifying your link…</span>
        </Card.Body>
      </Card>
    );
  }

  if (status === "error") {
    return (
      <Alert variant="danger">
        {error || "Could not verify your link."}
      </Alert>
    );
  }

  if (status === "success" && apiKey) {
    return (
      <Card border="success">
        <Card.Header className="bg-success text-white">Your API key</Card.Header>
        <Card.Body>
          <Alert variant="warning" className="mb-3">
            <strong>Save this key now — it will not be shown again.</strong> Store it
            somewhere safe; if you lose it you must request a new one.
          </Alert>
          <div
            className="snippet-wrap"
            style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}
          >
            <code
              className="snippet-block"
              style={{ flexGrow: 1, whiteSpace: "normal", wordBreak: "break-all" }}
            >
              {apiKey}
            </code>
            <CopyButton value={apiKey} label="API key" logEvent="copy_api_key" />
          </div>
          <p className="text-muted mt-3 mb-0">
            Next: add the MCP server to your client using the snippets below (your key is
            already filled in).
          </p>
        </Card.Body>
      </Card>
    );
  }

  return null;
};

// ---- Keyless quick start (zero-setup default) ------------------------------

const KeylessSection: React.FC<{ mcpUrl: string | null }> = ({ mcpUrl }) => {
  const [active, setActive] = useState<string>(KEYLESS_SETUP_SNIPPETS[0].id);
  const urlValue = mcpUrl ?? MCP_HTTP_URL;

  const activeSnippet =
    KEYLESS_SETUP_SNIPPETS.find((s) => s.id === active) ?? KEYLESS_SETUP_SNIPPETS[0];
  const rendered = activeSnippet.template.replace(/\{URL\}/g, urlValue);

  return (
    <Card>
      <Card.Header>
        Start now — no key needed <Badge bg="success">keyless</Badge>
      </Card.Header>
      <Card.Body>
        <p className="text-muted">
          Add the endpoint to any MCP-capable agent and start asking about the
          podcasts immediately. Keyless access has a daily per-IP quota; get a free
          key below for higher limits.
        </p>
        <Nav
          variant="tabs"
          activeKey={active}
          onSelect={(k) => setActive(k || KEYLESS_SETUP_SNIPPETS[0].id)}
          className="mb-3"
        >
          {KEYLESS_SETUP_SNIPPETS.map((s) => (
            <Nav.Item key={s.id}>
              <Nav.Link eventKey={s.id}>{s.label}</Nav.Link>
            </Nav.Item>
          ))}
        </Nav>
        <div className="snippet-wrap">
          <div className="snippet-copy">
            <CopyButton
              value={rendered}
              label={`${activeSnippet.label} keyless config`}
              logEvent="copy_keyless_snippet"
            />
          </div>
          <pre className="snippet-block">{rendered}</pre>
        </div>
      </Card.Body>
    </Card>
  );
};

// ---- Setup snippets (tabbed) ---------------------------------------------

const SetupSection: React.FC<{ apiKey: string | null; mcpUrl: string | null }> = ({
  apiKey,
  mcpUrl,
}) => {
  const [active, setActive] = useState<string>(SETUP_SNIPPETS[0].id);
  const keyValue = apiKey ?? API_KEY_PLACEHOLDER;
  // Prefer the backend-supplied endpoint; fall back to the constant (F3).
  const urlValue = mcpUrl ?? MCP_HTTP_URL;

  const activeSnippet =
    SETUP_SNIPPETS.find((s) => s.id === active) ?? SETUP_SNIPPETS[0];
  const rendered = activeSnippet.template
    .replace(/\{KEY\}/g, keyValue)
    .replace(/\{URL\}/g, urlValue);

  return (
    <Card>
      <Card.Header>Connect with your API key (higher limits)</Card.Header>
      <Card.Body>
        <p className="text-muted">
          One-time, copy-paste setup for keyed access. Replace{" "}
          <code>{API_KEY_PLACEHOLDER}</code> with your issued key if it is not already
          filled in. The endpoint is <code>{urlValue}</code>.
        </p>
        <Nav
          variant="tabs"
          activeKey={active}
          onSelect={(k) => setActive(k || SETUP_SNIPPETS[0].id)}
          className="mb-3"
        >
          {SETUP_SNIPPETS.map((s) => (
            <Nav.Item key={s.id}>
              <Nav.Link eventKey={s.id}>{s.label}</Nav.Link>
            </Nav.Item>
          ))}
        </Nav>
        <div className="snippet-wrap">
          <div className="snippet-copy">
            <CopyButton
              value={rendered}
              label={`${activeSnippet.label} config`}
              logEvent="copy_snippet"
            />
          </div>
          <pre className="snippet-block">{rendered}</pre>
        </div>
      </Card.Body>
    </Card>
  );
};

// ---- Tools list ----------------------------------------------------------

const ToolsSection: React.FC = () => (
  <Card>
    <Card.Header>Available tools</Card.Header>
    <Card.Body className="d-flex flex-column gap-3">
      {MCP_TOOLS.map((tool) => (
        <div key={tool.name}>
          <div className="tool-sig">{tool.signature}</div>
          <div className="text-muted">{tool.description}</div>
        </div>
      ))}
    </Card.Body>
  </Card>
);

// ---- FAQ -----------------------------------------------------------------

const FaqSection: React.FC = () => (
  <Card>
    <Card.Header>
      FAQ <Badge bg="secondary">search-only</Badge>
    </Card.Header>
    <Card.Body className="d-flex flex-column gap-3">
      {PODCAST_FAQ.map((item) => (
        <div key={item.q}>
          <div className="fw-bold">{item.q}</div>
          <div className="text-muted">{item.a}</div>
        </div>
      ))}
    </Card.Body>
  </Card>
);
