/**
 * Tests for the SSE parser + reducer of useAgentStream.
 *
 * We test `agentStreamReducer` and `dispatchSSEChunk` directly — these
 * encode the event-taxonomy contract with the backend. Driving the
 * fetch loop end-to-end requires mocking ReadableStream + TextDecoder
 * and is covered by the integration test on the backend side.
 */

import { agentStreamReducer, dispatchSSEChunk } from "../useAgentStream";
import { AgentEventType } from "../../types/agent";

const INITIAL = agentStreamReducer(undefined as any, { type: "reset" } as any);

function feed(chunks: string[]) {
  const actions: any[] = [];
  for (const chunk of chunks) {
    dispatchSSEChunk(chunk, (a) => actions.push(a));
  }
  return actions.reduce(
    (s, a) => agentStreamReducer(s, a),
    { ...INITIAL, isStreaming: true }
  );
}

describe("agentStreamReducer + dispatchSSEChunk", () => {
  test("token events accumulate into assistantText", () => {
    const state = feed([
      `event: ${AgentEventType.Token}\ndata: ${JSON.stringify({ token: "Hello, " })}`,
      `event: ${AgentEventType.Token}\ndata: ${JSON.stringify({ token: "world." })}`,
    ]);
    expect(state.assistantText).toBe("Hello, world.");
  });

  test("tool_call_started + tool_call_finished round trip by call_id", () => {
    const state = feed([
      `event: ${AgentEventType.ToolCallStarted}\ndata: ${JSON.stringify({
        call_id: "c1",
        tool: "list_my_communities",
        args: {},
      })}`,
      `event: ${AgentEventType.ToolCallFinished}\ndata: ${JSON.stringify({
        call_id: "c1",
        status: "success",
        result_summary: '["mcp_israel"]',
      })}`,
    ]);
    expect(state.toolCalls["c1"]).toBeDefined();
    expect(state.toolCalls["c1"].tool).toBe("list_my_communities");
    expect(state.toolCalls["c1"].status).toBe("success");
    expect(state.toolCalls["c1"].result_summary).toContain("mcp_israel");
  });

  test("tool_call_finished with status='error' surfaces as error", () => {
    const state = feed([
      `event: ${AgentEventType.ToolCallStarted}\ndata: ${JSON.stringify({
        call_id: "c2",
        tool: "describe_community",
        args: { community_key: "langtalks" },
      })}`,
      `event: ${AgentEventType.ToolCallFinished}\ndata: ${JSON.stringify({
        call_id: "c2",
        status: "error",
        result_summary: "Permission denied: you do not own 'langtalks'.",
      })}`,
    ]);
    expect(state.toolCalls["c2"].status).toBe("error");
    expect(state.toolCalls["c2"].result_summary).toContain("Permission denied");
  });

  test("artifact_panel events accumulate", () => {
    const state = feed([
      `event: ${AgentEventType.ArtifactPanel}\ndata: ${JSON.stringify({
        component: "ProgressTracker",
        props: { run_id: "r1" },
      })}`,
      `event: ${AgentEventType.ArtifactPanel}\ndata: ${JSON.stringify({
        component: "RunsBrowser",
        props: {},
      })}`,
    ]);
    expect(state.artifactPanels).toHaveLength(2);
    expect(state.artifactPanels[0].component).toBe("ProgressTracker");
    expect(state.artifactPanels[1].component).toBe("RunsBrowser");
  });

  test("interrupt_required surfaces the payload", () => {
    const payload = {
      kind: "confirm",
      action: "delete_schedule",
      args: { schedule_id: "s1" },
    };
    const state = feed([
      `event: ${AgentEventType.InterruptRequired}\ndata: ${JSON.stringify(payload)}`,
    ]);
    expect(state.pendingInterrupt).toEqual(payload);
  });

  test("error event flips isStreaming off and records the message", () => {
    const state = feed([
      `event: ${AgentEventType.Error}\ndata: ${JSON.stringify({ error: "boom" })}`,
    ]);
    expect(state.isStreaming).toBe(false);
    expect(state.error).toBe("boom");
  });

  test("done event flips isStreaming off and sets done", () => {
    const state = feed([
      `event: ${AgentEventType.Done}\ndata: ${JSON.stringify({})}`,
    ]);
    expect(state.isStreaming).toBe(false);
    expect(state.done).toBe(true);
  });

  test("unknown event types are ignored (no crash, no state mutation)", () => {
    const state = feed([
      `event: this_event_does_not_exist\ndata: ${JSON.stringify({ x: 1 })}`,
    ]);
    expect(state.assistantText).toBe("");
    expect(state.error).toBeNull();
  });

  test("malformed data (non-JSON) does not crash", () => {
    const actions: any[] = [];
    dispatchSSEChunk(
      `event: ${AgentEventType.Token}\ndata: not-valid-json`,
      (a) => actions.push(a)
    );
    // The parser should still emit a token action, with the raw string
    // coerced to empty token (we expect {token: undefined} → "").
    expect(actions[0]?.type).toBe("token");
  });

  test("multi-line data parses correctly", () => {
    const chunk =
      `event: ${AgentEventType.Token}\n` +
      `data: ${JSON.stringify({ token: "line1" })}`;
    const actions: any[] = [];
    dispatchSSEChunk(chunk, (a) => actions.push(a));
    expect(actions).toEqual([{ type: "token", token: "line1" }]);
  });
});

describe("agentStreamReducer reset", () => {
  test("reset clears state", () => {
    const halfway = feed([
      `event: ${AgentEventType.Token}\ndata: ${JSON.stringify({ token: "x" })}`,
    ]);
    const reset = agentStreamReducer(halfway, { type: "reset" });
    expect(reset.assistantText).toBe("");
    expect(reset.toolCalls).toEqual({});
    expect(reset.isStreaming).toBe(false);
    expect(reset.done).toBe(false);
  });
});
