/**
 * UsersAdmin tests:
 *  - renders the user list from a mocked API
 *  - create-user 409 surfaces the duplicate-email error inline
 *  - non-admin renders the access note
 */

import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from "@testing-library/react";

import { UsersAdmin } from "./UsersAdmin";
import { AuthContext } from "../../contexts/AuthContext";
import type { AuthContextValue } from "../../contexts/AuthContext";

const ORIG_FETCH = global.fetch;

afterEach(() => {
  global.fetch = ORIG_FETCH;
  jest.restoreAllMocks();
});

function mockFetch(impl: jest.Mock) {
  global.fetch = impl as unknown as typeof fetch;
}

function renderWithAuth(
  ui: React.ReactElement,
  overrides: Partial<AuthContextValue> = {}
) {
  const value: AuthContextValue = {
    status: "authenticated",
    currentUser: { email: "admin@example.com", role: "admin" },
    isAdmin: true,
    login: jest.fn(async () => undefined),
    logout: jest.fn(async () => undefined),
    ...overrides,
  };
  return render(
    <AuthContext.Provider value={value}>{ui}</AuthContext.Provider>
  );
}

const SAMPLE_USERS = [
  {
    user_id: "u1",
    email: "alice@example.com",
    role: "admin",
    communities: ["langtalks"],
    disabled: false,
  },
  {
    user_id: "u2",
    email: "bob@example.com",
    role: "viewer",
    communities: [],
    disabled: true,
  },
];

test("renders the user list returned by the API", async () => {
  const fetchMock = jest.fn(async (url: string) => {
    if (url.includes("/api/auth/users")) {
      return {
        ok: true,
        status: 200,
        json: async () => SAMPLE_USERS,
      } as Response;
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  mockFetch(fetchMock);

  renderWithAuth(<UsersAdmin />);

  expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  expect(screen.getByTestId("user-row-u1")).toBeInTheDocument();
  expect(screen.getByTestId("user-row-u2")).toBeInTheDocument();
});

test("create-user 409 surfaces the duplicate email error inline", async () => {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.includes("/api/auth/users")) {
      return { ok: false, status: 409, json: async () => ({}) } as Response;
    }
    // GET list (initial + any refresh)
    return {
      ok: true,
      status: 200,
      json: async () => SAMPLE_USERS,
    } as Response;
  });
  mockFetch(fetchMock);

  renderWithAuth(<UsersAdmin />);
  await screen.findByTestId("user-row-u1");

  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "alice@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "secret123" },
  });
  fireEvent.click(screen.getByRole("button", { name: /create user/i }));

  const errorAlert = await screen.findByTestId("create-user-error");
  expect(errorAlert).toHaveTextContent(/already exists/i);
});

test("non-admin renders the access note", () => {
  renderWithAuth(<UsersAdmin />, {
    isAdmin: false,
    currentUser: { email: "viewer@example.com", role: "viewer" },
  });

  expect(
    screen.getByTestId("users-admin-access-note")
  ).toBeInTheDocument();
  expect(screen.queryByTestId("users-table")).toBeNull();
});
