/**
 * AuthContext tests for the individual-account contract:
 *  - the session probe populates currentUser + isAdmin from the response body
 *  - login POSTs {email, password} and updates currentUser
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AuthProvider, useAuth } from "./AuthContext";

const ORIG_FETCH = global.fetch;

afterEach(() => {
  global.fetch = ORIG_FETCH;
  jest.restoreAllMocks();
});

function mockFetch(impl: jest.Mock) {
  global.fetch = impl as unknown as typeof fetch;
}

const Probe: React.FC = () => {
  const { status, currentUser, isAdmin, login } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="email">{currentUser?.email ?? "none"}</span>
      <span data-testid="role">{currentUser?.role ?? "none"}</span>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
      <button onClick={() => void login("u@example.com", "pw")}>login</button>
    </div>
  );
};

test("session probe populates currentUser and isAdmin from the body", async () => {
  const fetchMock = jest.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ authenticated: true, email: "a@x.com", role: "admin" }),
  }) as Response);
  mockFetch(fetchMock);

  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated")
  );
  expect(screen.getByTestId("email")).toHaveTextContent("a@x.com");
  expect(screen.getByTestId("role")).toHaveTextContent("admin");
  expect(screen.getByTestId("isAdmin")).toHaveTextContent("true");
});

test("login posts {email, password} and stores the returned user", async () => {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/api/auth/session")) {
      return { ok: false, status: 401, json: async () => ({}) } as Response;
    }
    if (url.includes("/api/auth/login")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          email: "u@example.com",
          role: "viewer",
        }),
      } as Response;
    }
    throw new Error(`unexpected ${url}`);
  });
  mockFetch(fetchMock);

  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated")
  );

  fireEvent.click(screen.getByText("login"));

  await waitFor(() =>
    expect(screen.getByTestId("email")).toHaveTextContent("u@example.com")
  );
  expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  expect(screen.getByTestId("isAdmin")).toHaveTextContent("false");

  const loginCall = fetchMock.mock.calls.find((c) =>
    String(c[0]).includes("/api/auth/login")
  );
  expect(loginCall).toBeDefined();
  const body = JSON.parse((loginCall![1] as RequestInit).body as string);
  expect(body).toEqual({ email: "u@example.com", password: "pw" });
});
