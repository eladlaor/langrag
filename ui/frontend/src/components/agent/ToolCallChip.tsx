/**
 * ToolCallChip — inline pill showing one tool invocation in the agent
 * message stream. Renders the tool name + status (running / success /
 * error). The args are redacted server-side before SSE emission.
 */

import React from "react";

import { ToolCallChipState } from "../../types/agent";

interface Props {
  state: ToolCallChipState;
}

const STATUS_COLOR: Record<string, string> = {
  running: "#6b7280",
  success: "#16a34a",
  error: "#dc2626",
};

export const ToolCallChip: React.FC<Props> = ({ state }) => {
  return (
    <span
      data-testid={`tool-chip-${state.call_id}`}
      style={{
        display: "inline-block",
        padding: "2px 8px",
        margin: "2px 4px 2px 0",
        borderRadius: 12,
        backgroundColor: "#f3f4f6",
        border: `1px solid ${STATUS_COLOR[state.status] || "#d1d5db"}`,
        fontSize: 12,
        fontFamily: "monospace",
      }}
      title={state.result_summary || ""}
    >
      <span style={{ color: STATUS_COLOR[state.status] }}>
        {state.status === "running" ? "▶" : state.status === "success" ? "✓" : "✗"}
      </span>{" "}
      {state.tool}
    </span>
  );
};
