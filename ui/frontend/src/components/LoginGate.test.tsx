/**
 * LoginGate tests for the self-signup surface:
 *  - Sign In <-> Create account toggle (shown when signup is enabled)
 *  - the RejectionScreen renders when signup() yields a not_allowlisted result
 *  - the contact form POSTs to /api/auth/access-requests and confirms success
 *  - the gate starts on the rejection screen when ?signup=rejected&email= is set
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { LoginGate } from "./LoginGate";
import { AuthProvider } from "../contexts/AuthContext";
import {
  SIGNUP_CODE_NOT_ALLOWLISTED,
  AUTH_ROUTES,
} from "../constants";

const ORIG_FETCH = global.fetch;

afterEach(() => {
  global.fetch = ORIG_FETCH;
  jest.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function mockFetch(impl: jest.Mock) {
  global.fetch = impl as unknown as typeof fetch;
}

/** Session=401 (unauthenticated), config enables signup. Per-test signup/access overrides. */
function baseFetch(
  overrides: (url: string, init?: RequestInit) => Response | undefined
): jest.Mock {
  return jest.fn(async (url: string, init?: RequestInit) => {
    const o = overrides(url, init);
    if (o) return o;
    if (url.includes(AUTH_ROUTES.SESSION)) {
      return { ok: false, status: 401, json: async () => ({}) } as Response;
    }
    if (url.includes(AUTH_ROUTES.CONFIG)) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ google_enabled: true, signup_enabled: true }),
      } as Response;
    }
    throw new Error(`unexpected ${url}`);
  });
}

test("toggles between Sign In and Create account", async () => {
  mockFetch(baseFetch(() => undefined));

  render(
    <AuthProvider>
      <LoginGate>
        <div>protected</div>
      </LoginGate>
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("toggle-to-signup")).toBeInTheDocument()
  );
  fireEvent.click(screen.getByTestId("toggle-to-signup"));

  expect(screen.getByTestId("signup-confirm")).toBeInTheDocument();
  expect(screen.getByTestId("signup-submit")).toBeInTheDocument();

  fireEvent.click(screen.getByTestId("toggle-to-signin"));
  expect(screen.queryByTestId("signup-confirm")).not.toBeInTheDocument();
});

test("shows the Continue with Google button when google is enabled", async () => {
  mockFetch(baseFetch(() => undefined));
  render(
    <AuthProvider>
      <LoginGate>
        <div>protected</div>
      </LoginGate>
    </AuthProvider>
  );
  await waitFor(() =>
    expect(screen.getByTestId("google-login-btn")).toBeInTheDocument()
  );
});

test("renders the RejectionScreen on a not_allowlisted signup", async () => {
  const fetchMock = baseFetch((url) => {
    if (url.includes(AUTH_ROUTES.SIGNUP)) {
      return {
        ok: false,
        status: 403,
        json: async () => ({
          detail: { message: "nope", code: SIGNUP_CODE_NOT_ALLOWLISTED },
        }),
      } as Response;
    }
    return undefined;
  });
  mockFetch(fetchMock);

  render(
    <AuthProvider>
      <LoginGate>
        <div>protected</div>
      </LoginGate>
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("toggle-to-signup")).toBeInTheDocument()
  );
  fireEvent.click(screen.getByTestId("toggle-to-signup"));

  fireEvent.change(screen.getByTestId("signup-email"), {
    target: { value: "nope@example.com" },
  });
  fireEvent.change(screen.getByTestId("signup-password"), {
    target: { value: "pw123456" },
  });
  fireEvent.change(screen.getByTestId("signup-confirm"), {
    target: { value: "pw123456" },
  });
  fireEvent.click(screen.getByTestId("signup-submit"));

  await waitFor(() =>
    expect(screen.getByTestId("rejection-screen")).toBeInTheDocument()
  );
  // Email is prefilled from the failed attempt.
  expect(screen.getByTestId("access-request-email")).toHaveValue(
    "nope@example.com"
  );
});

test("contact form POSTs to access-requests and confirms success", async () => {
  const fetchMock = baseFetch((url) => {
    if (url.includes(AUTH_ROUTES.SIGNUP)) {
      return {
        ok: false,
        status: 403,
        json: async () => ({
          detail: { message: "nope", code: SIGNUP_CODE_NOT_ALLOWLISTED },
        }),
      } as Response;
    }
    if (url.includes(AUTH_ROUTES.ACCESS_REQUESTS)) {
      return {
        ok: true,
        status: 201,
        json: async () => ({ message: "received" }),
      } as Response;
    }
    return undefined;
  });
  mockFetch(fetchMock);

  render(
    <AuthProvider>
      <LoginGate>
        <div>protected</div>
      </LoginGate>
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("toggle-to-signup")).toBeInTheDocument()
  );
  fireEvent.click(screen.getByTestId("toggle-to-signup"));
  fireEvent.change(screen.getByTestId("signup-email"), {
    target: { value: "nope@example.com" },
  });
  fireEvent.change(screen.getByTestId("signup-password"), {
    target: { value: "pw123456" },
  });
  fireEvent.change(screen.getByTestId("signup-confirm"), {
    target: { value: "pw123456" },
  });
  fireEvent.click(screen.getByTestId("signup-submit"));

  await waitFor(() =>
    expect(screen.getByTestId("access-request-submit")).toBeInTheDocument()
  );

  fireEvent.change(screen.getByTestId("access-request-message"), {
    target: { value: "please let me in" },
  });
  fireEvent.click(screen.getByTestId("access-request-submit"));

  await waitFor(() =>
    expect(
      screen.getByTestId("rejection-screen-submitted")
    ).toBeInTheDocument()
  );

  const reqCall = fetchMock.mock.calls.find((c) =>
    String(c[0]).includes(AUTH_ROUTES.ACCESS_REQUESTS)
  );
  expect(reqCall).toBeDefined();
  const body = JSON.parse((reqCall![1] as RequestInit).body as string);
  expect(body.email).toBe("nope@example.com");
  expect(body.message).toBe("please let me in");
});

test("starts on the rejection screen when ?signup=rejected is present", async () => {
  window.history.replaceState(
    null,
    "",
    "/?signup=rejected&email=g%40example.com"
  );
  mockFetch(baseFetch(() => undefined));

  render(
    <AuthProvider>
      <LoginGate>
        <div>protected</div>
      </LoginGate>
    </AuthProvider>
  );

  await waitFor(() =>
    expect(screen.getByTestId("rejection-screen")).toBeInTheDocument()
  );
  expect(screen.getByTestId("access-request-email")).toHaveValue(
    "g@example.com"
  );
  // The query is cleaned so a refresh does not re-trigger the screen.
  expect(window.location.search).toBe("");
});
