/**
 * RagPreferencesSlider — the saved per-user RAG MMR lambda control.
 *
 * A raw lambda slider (0.0–1.0, step 0.05) labeled "precise ↔ diverse".
 * Higher lambda = answers stay tightly on-topic; lower = more varied angles.
 *
 * Lifecycle:
 *   - On mount: GET /api/agent/rag-preferences to hydrate.
 *   - On change: debounced PUT to persist (the saved per-user setting).
 * All loads and writes emit structured logs (frontend logging convention).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import { agentApi } from "../../services/api";
import { logger } from "../../utils/logger";

interface Props {
  apiKey: string;
}

const PERSIST_DEBOUNCE_MS = 400;
const LAMBDA_STEP = 0.05;

export const RagPreferencesSlider: React.FC<Props> = ({ apiKey }) => {
  const [lambda, setLambda] = useState<number>(0.7);
  const [enabled, setEnabled] = useState<boolean>(true);
  const [loaded, setLoaded] = useState<boolean>(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prefs = await agentApi.getRagPreferences(apiKey);
        if (cancelled) {
          return;
        }
        setLambda(prefs.mmr_lambda);
        setEnabled(prefs.enable_mmr_diversity);
        setLoaded(true);
        logger.info("rag_preferences_loaded", {
          event: "rag_preferences_loaded",
          mmr_lambda: prefs.mmr_lambda,
          enable_mmr_diversity: prefs.enable_mmr_diversity,
        });
      } catch (err) {
        logger.error("rag_preferences_load_failed", {
          event: "rag_preferences_load_failed",
          error: err instanceof Error ? err.message : String(err),
        });
        // Deliberately leave `loaded` false: keep the controls disabled so a
        // transient GET failure can't let an edit PUT (and overwrite) a saved
        // value we never managed to read.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiKey]);

  const persist = useCallback(
    (nextLambda: number, nextEnabled: boolean) => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(async () => {
        try {
          await agentApi.setRagPreferences(apiKey, {
            mmr_lambda: nextLambda,
            enable_mmr_diversity: nextEnabled,
          });
          logger.info("rag_preferences_saved", {
            event: "rag_preferences_saved",
            mmr_lambda: nextLambda,
            enable_mmr_diversity: nextEnabled,
          });
        } catch (err) {
          logger.error("rag_preferences_save_failed", {
            event: "rag_preferences_save_failed",
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }, PERSIST_DEBOUNCE_MS);
    },
    [apiKey]
  );

  const onLambdaChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = Number(e.target.value);
      setLambda(next);
      persist(next, enabled);
    },
    [enabled, persist]
  );

  const onEnabledChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = e.target.checked;
      setEnabled(next);
      persist(lambda, next);
    },
    [lambda, persist]
  );

  return (
    <div
      data-testid="rag-preferences-slider"
      style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}
      title="Higher = answers stay on-topic. Lower = more varied angles."
    >
      <label style={{ color: "#6b7280" }}>
        <input
          type="checkbox"
          checked={enabled}
          disabled={!loaded}
          onChange={onEnabledChange}
          data-testid="rag-mmr-enabled"
        />{" "}
        diversity
      </label>
      <span style={{ color: "#6b7280" }}>precise</span>
      <input
        type="range"
        min={0}
        max={1}
        step={LAMBDA_STEP}
        value={lambda}
        disabled={!loaded || !enabled}
        onChange={onLambdaChange}
        data-testid="rag-mmr-lambda"
        aria-label="Answer focus: precise to diverse"
      />
      <span style={{ color: "#6b7280" }}>diverse</span>
      <code style={{ color: "#111827" }}>{lambda.toFixed(2)}</code>
    </div>
  );
};
