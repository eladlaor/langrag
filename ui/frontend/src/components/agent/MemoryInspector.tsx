/**
 * MemoryInspector — list + delete the current user's long-term memories.
 *
 * Non-negotiable for trust + GDPR: the user must be able to see what
 * the agent remembers about them and remove individual items. The list
 * is scoped to the authenticated user on the server (no user_id passed
 * client-side); deletes filter by user_id at the store layer.
 */

import React, { useCallback, useEffect, useState } from "react";

import { API_BASE_URL } from "../../constants";
import { AgentMemoryItem } from "../../types/agent";

interface Props {
  apiKey: string;
  namespace?: string;
}

export const MemoryInspector: React.FC<Props> = ({ apiKey, namespace }) => {
  const [items, setItems] = useState<AgentMemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = namespace ? `?namespace=${encodeURIComponent(namespace)}` : "";
      const resp = await fetch(`${API_BASE_URL}/api/agent/memories${qs}`, {
        headers: { "X-API-Key": apiKey },
      });
      if (!resp.ok) {
        setError(`HTTP ${resp.status}`);
        return;
      }
      const data = (await resp.json()) as AgentMemoryItem[];
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, [apiKey, namespace]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = useCallback(
    async (memory_id: string) => {
      // Optimistic update: drop locally before the network call returns
      // so the UI feels instant. Server-side delete is idempotent so a
      // failure is recoverable on next load().
      const previous = items;
      setItems((cur) => cur.filter((m) => m.memory_id !== memory_id));
      try {
        const resp = await fetch(
          `${API_BASE_URL}/api/agent/memories/${encodeURIComponent(memory_id)}`,
          {
            method: "DELETE",
            headers: { "X-API-Key": apiKey },
          }
        );
        if (!resp.ok) {
          setItems(previous);
          setError(`delete failed: HTTP ${resp.status}`);
        }
      } catch (e) {
        setItems(previous);
        setError(e instanceof Error ? e.message : "delete failed");
      }
    },
    [apiKey, items]
  );

  return (
    <div data-testid="memory-inspector">
      <h3 style={{ marginTop: 0 }}>What I remember about you</h3>
      {error && (
        <div style={{ color: "#dc2626" }} data-testid="memory-error">
          {error}
        </div>
      )}
      {loading && <div>Loading…</div>}
      {!loading && items.length === 0 && <div>No memories stored yet.</div>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {items.map((m) => (
          <li
            key={m.memory_id}
            data-testid={`memory-item-${m.memory_id}`}
            style={{
              padding: "8px 0",
              borderBottom: "1px solid #e5e7eb",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span
              style={{
                fontSize: 11,
                padding: "2px 6px",
                borderRadius: 8,
                backgroundColor: "#f3f4f6",
                fontFamily: "monospace",
              }}
            >
              {m.namespace}
            </span>
            <span style={{ flex: 1 }}>{m.content}</span>
            <button
              onClick={() => void remove(m.memory_id)}
              data-testid={`memory-delete-${m.memory_id}`}
              aria-label={`Delete memory ${m.memory_id}`}
            >
              Forget
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};
