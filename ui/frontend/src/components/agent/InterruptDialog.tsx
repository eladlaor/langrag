/**
 * InterruptDialog — HITL confirm modal. When the agent emits an
 * `interrupt_required` SSE event (commit 10 wires destructive tools
 * to this path), the chat container pops this modal and waits for
 * the user's approve / reject before POSTing /api/agent/chat/resume.
 */

import React from "react";

import { InterruptPayload } from "../../types/agent";

interface Props {
  payload: InterruptPayload;
  onApprove: () => void;
  onReject: () => void;
}

export const InterruptDialog: React.FC<Props> = ({
  payload,
  onApprove,
  onReject,
}) => {
  return (
    <div
      data-testid="interrupt-dialog"
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100vw",
        height: "100vh",
        backgroundColor: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          backgroundColor: "white",
          padding: 20,
          borderRadius: 8,
          width: 480,
          maxWidth: "90vw",
        }}
      >
        <h3 style={{ marginTop: 0 }}>Confirm action</h3>
        <p>The agent wants to perform a destructive action:</p>
        <pre
          style={{
            backgroundColor: "#f3f4f6",
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflowX: "auto",
          }}
        >
          {JSON.stringify(
            { action: payload.action, args: payload.args },
            null,
            2
          )}
        </pre>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onReject} data-testid="interrupt-reject">
            Reject
          </button>
          <button onClick={onApprove} data-testid="interrupt-approve">
            Approve
          </button>
        </div>
      </div>
    </div>
  );
};
