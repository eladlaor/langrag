/**
 * AuthContext - individual-account (email + password) login state.
 *
 * On mount it probes GET /api/auth/session (the backend validates the HttpOnly
 * Fernet session cookie and returns the current user's email+role). The whole
 * UI is gated on `status`:
 *   - 'checking'        -> session probe in flight
 *   - 'authenticated'   -> valid session cookie, render the real App
 *   - 'unauthenticated' -> show the login card
 *
 * Email + password are POSTed once to /api/auth/login; the server sets the
 * HttpOnly cookie. The plaintext password never lives in React state beyond
 * the in-flight request and is never persisted. `currentUser`/`isAdmin` expose
 * the authenticated identity for role-gated UI (the server remains the real
 * authorization boundary).
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  AUTH_ROUTES,
  FETCH_CREDENTIALS,
  HEADER_CONTENT_TYPE,
  CONTENT_TYPE_JSON,
  SESSION_EXPIRED_EVENT,
  ROLE_ADMIN,
  SIGNUP_CODE_NOT_ALLOWLISTED,
  SIGNUP_REJECTED_QUERY_PARAM,
  SIGNUP_REJECTED_QUERY_VALUE,
  SIGNUP_REJECTED_EMAIL_PARAM,
} from "../constants";
import { logger } from "../utils/logger";

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

export interface CurrentUser {
  email: string;
  role: string;
}

/**
 * Distinguishable error thrown by signup() when the backend rejects the email
 * with a 403 whose `detail.code === "not_allowlisted"`. The gate catches this
 * specific class to switch to the invite-only RejectionScreen instead of
 * rendering a generic error.
 */
export class NotAllowlistedError extends Error {
  readonly code = SIGNUP_CODE_NOT_ALLOWLISTED;
  constructor(message = "not_allowlisted") {
    super(message);
    this.name = "NotAllowlistedError";
  }
}

/**
 * Public config booleans from GET /api/auth/config, so the gate never renders
 * a dead Google button or a signup toggle the backend has disabled.
 */
export interface AuthConfig {
  googleEnabled: boolean;
  signupEnabled: boolean;
}

/**
 * When the Google OAuth callback redirects a non-allowlisted user back to the
 * SPA (`/?signup=rejected&email=...`), this carries the prefilled email so the
 * gate can show the RejectionScreen on mount.
 */
export interface RejectedSignup {
  email: string;
}

export interface AuthContextValue {
  status: AuthStatus;
  currentUser: CurrentUser | null;
  isAdmin: boolean;
  config: AuthConfig;
  rejectedSignup: RejectedSignup | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  loginWithGoogle: () => void;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined
);

const LOG_COMPONENT = "AuthProvider";

/**
 * Read `?signup=rejected&email=...` from the current URL (set by the Google
 * OAuth callback for a non-allowlisted user) and, if present, strip the query
 * so a refresh does not re-trigger the rejection screen. Returns the prefilled
 * email or null.
 */
function readRejectedSignupFromUrl(): RejectedSignup | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get(SIGNUP_REJECTED_QUERY_PARAM) !== SIGNUP_REJECTED_QUERY_VALUE) {
      return null;
    }
    const email = params.get(SIGNUP_REJECTED_EMAIL_PARAM) ?? "";
    // Clean the query so a refresh does not re-trigger the rejection screen.
    params.delete(SIGNUP_REJECTED_QUERY_PARAM);
    params.delete(SIGNUP_REJECTED_EMAIL_PARAM);
    const query = params.toString();
    const cleanUrl =
      window.location.pathname + (query ? `?${query}` : "") + window.location.hash;
    window.history.replaceState(null, "", cleanUrl);
    logger.info("Signup rejection detected from URL", {
      component: LOG_COMPONENT,
      event: "signup_rejected_redirect",
    });
    return { email };
  } catch (error) {
    logger.error("Failed to parse signup rejection from URL", {
      component: LOG_COMPONENT,
      event: "signup_rejected_redirect",
      error: error instanceof Error ? error.message : "Unknown error",
    });
    return null;
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [config, setConfig] = useState<AuthConfig>({
    googleEnabled: false,
    signupEnabled: false,
  });
  // Read once on mount; the value is stable for the gate's lifetime.
  const [rejectedSignup] = useState<RejectedSignup | null>(() =>
    readRejectedSignupFromUrl()
  );

  // Probe the existing session cookie on mount.
  useEffect(() => {
    let cancelled = false;
    logger.info("Component mounted", { component: LOG_COMPONENT });

    const checkSession = async () => {
      logger.info("API call start", {
        component: LOG_COMPONENT,
        event: "session_check",
        route: AUTH_ROUTES.SESSION,
      });
      try {
        const response = await fetch(AUTH_ROUTES.SESSION, {
          method: "GET",
          credentials: FETCH_CREDENTIALS,
        });
        if (cancelled) return;

        if (response.ok) {
          const body = await response.json().catch(() => null);
          logger.info("API call success", {
            component: LOG_COMPONENT,
            event: "session_check",
            status: response.status,
            email: body?.email,
            role: body?.role,
          });
          if (body && body.email && body.role) {
            setCurrentUser({ email: body.email, role: body.role });
          }
          setStatus("authenticated");
        } else {
          logger.info("Session not authenticated", {
            component: LOG_COMPONENT,
            event: "session_check",
            status: response.status,
          });
          setStatus("unauthenticated");
        }
      } catch (error) {
        if (cancelled) return;
        logger.error("API call failure", {
          component: LOG_COMPONENT,
          event: "session_check",
          error: error instanceof Error ? error.message : "Unknown error",
        });
        // Network failure: treat as unauthenticated so the gate shows.
        setStatus("unauthenticated");
      }
    };

    checkSession();
    return () => {
      cancelled = true;
      logger.info("Component unmounted", { component: LOG_COMPONENT });
    };
  }, []);

  // React to mid-session 401s surfaced by the API layer.
  useEffect(() => {
    const onSessionExpired = () => {
      logger.warn("Session expired event received", {
        component: LOG_COMPONENT,
        event: "session_expired",
      });
      setStatus("unauthenticated");
      setCurrentUser(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
    return () =>
      window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
  }, []);

  // Fetch the public auth config so the gate only shows enabled options.
  useEffect(() => {
    let cancelled = false;
    const loadConfig = async () => {
      logger.info("API call start", {
        component: LOG_COMPONENT,
        event: "auth_config",
        route: AUTH_ROUTES.CONFIG,
      });
      try {
        const response = await fetch(AUTH_ROUTES.CONFIG, {
          method: "GET",
          credentials: FETCH_CREDENTIALS,
        });
        if (cancelled) return;
        if (response.ok) {
          const body = await response.json().catch(() => null);
          const next: AuthConfig = {
            googleEnabled: Boolean(body?.google_enabled),
            signupEnabled: Boolean(body?.signup_enabled),
          };
          setConfig(next);
          logger.info("API call success", {
            component: LOG_COMPONENT,
            event: "auth_config",
            status: response.status,
            googleEnabled: next.googleEnabled,
            signupEnabled: next.signupEnabled,
          });
        } else {
          logger.warn("API call failure", {
            component: LOG_COMPONENT,
            event: "auth_config",
            status: response.status,
          });
        }
      } catch (error) {
        if (cancelled) return;
        logger.error("API call failure", {
          component: LOG_COMPONENT,
          event: "auth_config",
          error: error instanceof Error ? error.message : "Unknown error",
        });
        // Leave config at safe defaults (both disabled) on failure.
      }
    };
    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string): Promise<void> => {
      logger.info("API call start", {
        component: LOG_COMPONENT,
        event: "login",
        route: AUTH_ROUTES.LOGIN,
        email,
      });
      try {
        const response = await fetch(AUTH_ROUTES.LOGIN, {
          method: "POST",
          credentials: FETCH_CREDENTIALS,
          headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
          body: JSON.stringify({ email, password }),
        });

        if (!response.ok) {
          logger.warn("API call failure", {
            component: LOG_COMPONENT,
            event: "login",
            status: response.status,
            email,
          });
          // Throw so the form can render the error Alert. Never log the password.
          throw new Error("login_failed");
        }

        const body = await response.json().catch(() => null);
        if (body && body.email && body.role) {
          setCurrentUser({ email: body.email, role: body.role });
        }
        logger.info("API call success", {
          component: LOG_COMPONENT,
          event: "login",
          status: response.status,
          email: body?.email,
          role: body?.role,
        });
        setStatus("authenticated");
      } catch (error) {
        logger.warn("Login attempt rejected", {
          component: LOG_COMPONENT,
          event: "login",
          error: error instanceof Error ? error.message : "Unknown error",
        });
        throw error;
      }
    },
    []
  );

  const signup = useCallback(
    async (email: string, password: string): Promise<void> => {
      logger.info("API call start", {
        component: LOG_COMPONENT,
        event: "signup",
        route: AUTH_ROUTES.SIGNUP,
        email,
      });
      try {
        const response = await fetch(AUTH_ROUTES.SIGNUP, {
          method: "POST",
          credentials: FETCH_CREDENTIALS,
          headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
          body: JSON.stringify({ email, password }),
        });

        if (!response.ok) {
          const body = await response.json().catch(() => null);
          // A 403 whose detail.code === "not_allowlisted" is the invite-only
          // rejection — distinguishable so the gate shows the RejectionScreen.
          const detail = body?.detail;
          const isNotAllowlisted =
            response.status === 403 &&
            detail !== null &&
            typeof detail === "object" &&
            detail.code === SIGNUP_CODE_NOT_ALLOWLISTED;
          if (isNotAllowlisted) {
            logger.warn("Signup rejected — not allowlisted", {
              component: LOG_COMPONENT,
              event: "signup",
              status: response.status,
              email,
            });
            throw new NotAllowlistedError();
          }
          logger.warn("API call failure", {
            component: LOG_COMPONENT,
            event: "signup",
            status: response.status,
            email,
          });
          // Generic failure (disabled signup, duplicate email, validation).
          throw new Error("signup_failed");
        }

        const body = await response.json().catch(() => null);
        if (body && body.email && body.role) {
          setCurrentUser({ email: body.email, role: body.role });
        }
        logger.info("API call success", {
          component: LOG_COMPONENT,
          event: "signup",
          status: response.status,
          email: body?.email,
          role: body?.role,
        });
        setStatus("authenticated");
      } catch (error) {
        logger.warn("Signup attempt rejected", {
          component: LOG_COMPONENT,
          event: "signup",
          error: error instanceof Error ? error.message : "Unknown error",
        });
        throw error;
      }
    },
    []
  );

  const loginWithGoogle = useCallback((): void => {
    logger.info("User interaction", {
      component: LOG_COMPONENT,
      event: "login_with_google",
      route: AUTH_ROUTES.GOOGLE_LOGIN,
    });
    // Full-page navigation: the backend issues a 302 to Google. A fetch would
    // not follow the cross-origin auth redirect, so we hand the browser over.
    window.location.href = AUTH_ROUTES.GOOGLE_LOGIN;
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    logger.info("API call start", {
      component: LOG_COMPONENT,
      event: "logout",
      route: AUTH_ROUTES.LOGOUT,
    });
    try {
      await fetch(AUTH_ROUTES.LOGOUT, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
      });
      logger.info("API call success", {
        component: LOG_COMPONENT,
        event: "logout",
      });
    } catch (error) {
      logger.error("API call failure", {
        component: LOG_COMPONENT,
        event: "logout",
        error: error instanceof Error ? error.message : "Unknown error",
      });
      // Even on a network error, drop the client to the gate.
    } finally {
      setStatus("unauthenticated");
      setCurrentUser(null);
    }
  }, []);

  const isAdmin = currentUser?.role === ROLE_ADMIN;

  return (
    <AuthContext.Provider
      value={{
        status,
        currentUser,
        isAdmin,
        config,
        rejectedSignup,
        login,
        signup,
        loginWithGoogle,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
