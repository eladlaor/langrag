/**
 * AgentKeyManager — mints, lists, and revokes the per-user agent API key,
 * then renders {@link AgentChat} once an active key is available.
 *
 * The agent chat endpoints authenticate with an `X-API-Key` header, but the
 * rest of the app uses a cookie session. This component bridges the two: it
 * calls the cookie-gated `/api/users/me/agent-keys` surface to provision a
 * key, holds the freshly-minted plaintext in `sessionStorage` (it is the only
 * time the backend returns it), and passes it down to AgentChat.
 *
 * The plaintext is intentionally NOT persisted to localStorage — it lives only
 * for the browser session, and a page reload after the issue moment requires
 * minting a new key (the old one stays valid; it just isn't retrievable).
 */

import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Form, Spinner, Table } from "react-bootstrap";

import { agentKeysApi, ApiError } from "../../services/api";
import { AgentApiKeySummary } from "../../types/agent";
import { logger } from "../../utils/logger";
import { AgentChat } from "./AgentChat";

const ACTIVE_KEY_STORAGE = "langrag.agent.activeKey";

export const AgentKeyManager: React.FC = () => {
  const [activeKey, setActiveKey] = useState<string | null>(() =>
    typeof window !== "undefined"
      ? window.sessionStorage.getItem(ACTIVE_KEY_STORAGE)
      : null
  );
  const [keys, setKeys] = useState<AgentApiKeySummary[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justIssued, setJustIssued] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setKeys(await agentKeysApi.list());
    } catch (e) {
      logger.error("agent key listing failed", { error: String(e) });
      setError("Could not load your API keys.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const persistActiveKey = useCallback((key: string | null) => {
    setActiveKey(key);
    if (typeof window === "undefined") return;
    if (key) {
      window.sessionStorage.setItem(ACTIVE_KEY_STORAGE, key);
    } else {
      window.sessionStorage.removeItem(ACTIVE_KEY_STORAGE);
    }
  }, []);

  const handleIssue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const issued = await agentKeysApi.issue(name.trim());
      logger.info("agent key issued", { key_id: issued.key_id });
      setJustIssued(issued.plaintext);
      persistActiveKey(issued.plaintext);
      setName("");
      await refresh();
    } catch (e) {
      const msg =
        e instanceof ApiError ? `Failed to issue key (HTTP ${e.status}).` : "Failed to issue key.";
      logger.error("agent key issue failed", { error: String(e) });
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [name, persistActiveKey, refresh]);

  const handleRevoke = useCallback(
    async (keyId: string) => {
      try {
        await agentKeysApi.revoke(keyId);
        logger.info("agent key revoked", { key_id: keyId });
        await refresh();
      } catch (e) {
        logger.error("agent key revoke failed", { key_id: keyId, error: String(e) });
        setError("Failed to revoke key.");
      }
    },
    [refresh]
  );

  return (
    <div className="d-flex flex-column gap-4">
      <Card>
        <Card.Header>Agent API keys</Card.Header>
        <Card.Body>
          <p className="text-muted">
            The agent chat authenticates with a personal API key. Generate one
            below; the secret is shown only once. It is kept for this browser
            session so you can chat immediately.
          </p>

          {error && <Alert variant="danger">{error}</Alert>}

          {justIssued && (
            <Alert variant="success" onClose={() => setJustIssued(null)} dismissible>
              <div className="fw-bold">New key (copy it now — shown once):</div>
              <code style={{ wordBreak: "break-all" }}>{justIssued}</code>
            </Alert>
          )}

          <Form
            className="d-flex gap-2 align-items-end mb-3"
            onSubmit={(e) => {
              e.preventDefault();
              void handleIssue();
            }}
          >
            <Form.Group className="flex-grow-1">
              <Form.Label>Key name (optional)</Form.Label>
              <Form.Control
                type="text"
                placeholder="e.g. laptop"
                value={name}
                maxLength={120}
                onChange={(e) => setName(e.target.value)}
              />
            </Form.Group>
            <Button type="submit" disabled={loading}>
              {loading ? <Spinner size="sm" /> : "Generate key"}
            </Button>
          </Form>

          {keys.length > 0 && (
            <Table size="sm" responsive>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Created</th>
                  <th>Last used</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.key_id}>
                    <td>{k.name || <span className="text-muted">(unnamed)</span>}</td>
                    <td>{k.created_at ? new Date(k.created_at).toLocaleString() : "—"}</td>
                    <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                    <td>{k.enabled ? "active" : "revoked"}</td>
                    <td className="text-end">
                      {k.enabled && (
                        <Button
                          variant="outline-danger"
                          size="sm"
                          onClick={() => void handleRevoke(k.key_id)}
                        >
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}

          {activeKey && (
            <div className="mt-2">
              <span className="badge bg-success">Active key loaded for this session</span>{" "}
              <Button variant="link" size="sm" onClick={() => persistActiveKey(null)}>
                clear
              </Button>
            </div>
          )}
        </Card.Body>
      </Card>

      {activeKey ? (
        <AgentChat apiKey={activeKey} />
      ) : (
        <Alert variant="info">Generate a key above to start chatting with the agent.</Alert>
      )}
    </div>
  );
};
