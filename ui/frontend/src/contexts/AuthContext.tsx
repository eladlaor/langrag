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
} from "../constants";
import { logger } from "../utils/logger";

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

export interface CurrentUser {
  email: string;
  role: string;
}

export interface AuthContextValue {
  status: AuthStatus;
  currentUser: CurrentUser | null;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined
);

const LOG_COMPONENT = "AuthProvider";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);

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
      value={{ status, currentUser, isAdmin, login, logout }}
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
