/**
 * AgentKeyManager tests: lists keys on mount, mints a key and surfaces the
 * one-time plaintext, then unlocks the chat once a key is active.
 *
 * AgentChat is mocked so the test stays focused on key management and does not
 * pull in the SSE streaming machinery.
 */

import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { AgentKeyManager } from "../AgentKeyManager";
import { agentKeysApi } from "../../../services/api";

jest.mock("../AgentChat", () => ({
  AgentChat: ({ apiKey }: { apiKey: string }) => (
    <div data-testid="agent-chat">chat with key {apiKey}</div>
  ),
}));

jest.mock("../../../services/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  agentKeysApi: {
    list: jest.fn(),
    issue: jest.fn(),
    revoke: jest.fn(),
  },
}));

const mockedApi = agentKeysApi as jest.Mocked<typeof agentKeysApi>;

beforeEach(() => {
  window.sessionStorage.clear();
  jest.clearAllMocks();
  mockedApi.list.mockResolvedValue([]);
});

test("prompts to generate a key when none is active", async () => {
  render(<AgentKeyManager />);
  await waitFor(() => expect(mockedApi.list).toHaveBeenCalled());
  expect(
    screen.getByText(/generate a key above to start chatting/i)
  ).toBeInTheDocument();
  expect(screen.queryByTestId("agent-chat")).not.toBeInTheDocument();
});

test("mints a key, shows the one-time plaintext, and unlocks chat", async () => {
  mockedApi.issue.mockResolvedValue({
    key_id: "k1",
    name: "laptop",
    plaintext: "lk_user_secret123",
  });
  mockedApi.list.mockResolvedValueOnce([]).mockResolvedValueOnce([
    {
      key_id: "k1",
      name: "laptop",
      enabled: true,
      created_at: null,
      last_used_at: null,
    },
  ]);

  render(<AgentKeyManager />);
  await waitFor(() => expect(mockedApi.list).toHaveBeenCalled());

  fireEvent.click(screen.getByRole("button", { name: /generate key/i }));

  await waitFor(() =>
    expect(screen.getByText("lk_user_secret123")).toBeInTheDocument()
  );
  expect(mockedApi.issue).toHaveBeenCalledTimes(1);
  expect(await screen.findByTestId("agent-chat")).toHaveTextContent(
    "lk_user_secret123"
  );
});
