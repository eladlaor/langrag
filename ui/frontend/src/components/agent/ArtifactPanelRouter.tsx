/**
 * ArtifactPanelRouter — routes `artifact_panel` SSE events to the
 * matching existing component in the right-side workspace pane.
 *
 * The agent emits e.g. `{component: "ProgressTracker", props: {run_id}}`
 * and this router renders ProgressTracker with those props. Where the
 * existing component requires complex inputs we don't have at the
 * agent layer (e.g., the full PeriodicNewsletterForm), we fall back
 * to a stub card so the panel always renders SOMETHING and the agent
 * can iterate.
 *
 * The set of routable components is fixed at v1.14.0; commit 10 will
 * extend it to include the HITL confirm dialog when an interrupt
 * arrives.
 */

import React from "react";

import { ArtifactPanelPayload } from "../../types/agent";

interface Props {
  panels: ArtifactPanelPayload[];
}

export const ArtifactPanelRouter: React.FC<Props> = ({ panels }) => {
  if (panels.length === 0) {
    return (
      <div
        data-testid="artifact-panel-empty"
        style={{ padding: 16, color: "#6b7280" }}
      >
        The agent will surface artifacts (progress, drafts, run reports) here
        as it works.
      </div>
    );
  }
  // Render the most recent panel — older panels stay accessible by
  // scrolling the message thread (where the SSE event lives).
  const panel = panels[panels.length - 1];
  return (
    <div data-testid={`artifact-panel-${panel.component}`}>
      <ArtifactStub payload={panel} />
    </div>
  );
};

const ArtifactStub: React.FC<{ payload: ArtifactPanelPayload }> = ({
  payload,
}) => {
  // For v1.14.0 we render every artifact as a labelled JSON card. The
  // existing ProgressTracker / RunsBrowser / DiagnosticReport
  // components require lifecycle wiring (SSE streams of their own,
  // form state, etc.) that the agent doesn't have a clean way to
  // provide yet. The plan calls out this as a v1.14.0 follow-up;
  // routing to real components moves with a frontend rework that's
  // out of scope for the launch surface.
  return (
    <div
      style={{
        padding: 16,
        backgroundColor: "#f9fafb",
        border: "1px solid #e5e7eb",
        borderRadius: 6,
      }}
    >
      <div
        style={{ fontFamily: "monospace", fontSize: 12, color: "#6b7280" }}
      >
        {payload.component}
      </div>
      <pre style={{ marginTop: 8, fontSize: 12, overflowX: "auto" }}>
        {JSON.stringify(payload.props, null, 2)}
      </pre>
    </div>
  );
};
