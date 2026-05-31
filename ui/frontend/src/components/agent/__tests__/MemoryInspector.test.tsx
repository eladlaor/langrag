/**
 * MemoryInspector tests: listing + optimistic delete + error rendering.
 */

import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";

import { MemoryInspector } from "../MemoryInspector";

const ORIG_FETCH = global.fetch;

afterEach(() => {
  global.fetch = ORIG_FETCH;
  jest.restoreAllMocks();
});

function mockFetch(impl: jest.Mock) {
  global.fetch = impl as unknown as typeof fetch;
}

test("renders memories returned by the API", async () => {
  const fetchMock = jest.fn(async (url: string) => {
    if (url.includes("/api/agent/memories")) {
      return {
        ok: true,
        status: 200,
        json: async () => [
          {
            memory_id: "m1",
            namespace: "semantic",
            content: "user prefers Hebrew",
            importance: 0.9,
          },
          {
            memory_id: "m2",
            namespace: "episodic",
            content: "rejected first draft",
            importance: 0.6,
          },
        ],
      } as Response;
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  mockFetch(fetchMock);

  render(<MemoryInspector apiKey="key-123" />);

  expect(await screen.findByText(/user prefers Hebrew/i)).toBeInTheDocument();
  expect(screen.getByText(/rejected first draft/i)).toBeInTheDocument();
  expect(screen.getByTestId("memory-item-m1")).toBeInTheDocument();
  expect(screen.getByTestId("memory-item-m2")).toBeInTheDocument();
});

test("optimistic delete removes the row before the network resolves", async () => {
  let resolveDelete: (v: any) => void;
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      return new Promise<Response>((res) => {
        resolveDelete = res;
      });
    }
    return {
      ok: true,
      status: 200,
      json: async () => [
        {
          memory_id: "m1",
          namespace: "semantic",
          content: "user prefers Hebrew",
          importance: 0.9,
        },
      ],
    } as Response;
  });
  mockFetch(fetchMock);

  render(<MemoryInspector apiKey="k" />);
  await screen.findByTestId("memory-item-m1");
  fireEvent.click(screen.getByTestId("memory-delete-m1"));
  // Row is gone immediately (optimistic).
  await waitFor(() =>
    expect(screen.queryByTestId("memory-item-m1")).toBeNull()
  );
  // Resolve the in-flight delete so the test exits cleanly.
  // @ts-expect-error — resolveDelete is assigned in the mock
  resolveDelete({ ok: true, status: 204 });
});

test("API failure surfaces an error and reverts optimistic delete", async () => {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      return { ok: false, status: 500 } as Response;
    }
    return {
      ok: true,
      status: 200,
      json: async () => [
        {
          memory_id: "m1",
          namespace: "semantic",
          content: "x",
          importance: 0.9,
        },
      ],
    } as Response;
  });
  mockFetch(fetchMock);

  render(<MemoryInspector apiKey="k" />);
  await screen.findByTestId("memory-item-m1");
  fireEvent.click(screen.getByTestId("memory-delete-m1"));
  await screen.findByTestId("memory-error");
  // Row should be back after the optimistic update is reverted.
  expect(screen.getByTestId("memory-item-m1")).toBeInTheDocument();
});
