/**
 * Public podcast-MCP consumer API client.
 *
 * These two endpoints power the standalone langrag.ai/podcasts page. They are
 * intentionally isolated from the main `api` client in ./api.ts:
 *   - They are PUBLIC (no app session), so requests carry NO cookie credentials.
 *   - They must NOT dispatch the SESSION_EXPIRED_EVENT on a non-2xx — a stranger
 *     on this page has no session to expire, and a 400/410 from verify is a
 *     normal outcome, not an auth failure.
 *
 * Responses are validated with Zod at the boundary before use.
 */

import { z } from "zod";

import { API_BASE_URL, HEADER_CONTENT_TYPE, CONTENT_TYPE_JSON } from "../constants";
import { PODCAST_CONSUMER_API_ROUTES } from "../constants/rag";

// ---- Wire schemas (validate what the backend actually returns) ----

// request-key always returns 202 with a generic message (no email enumeration).
const RequestKeyResponseSchema = z.object({
  message: z.string(),
});
export type RequestKeyResponse = z.infer<typeof RequestKeyResponseSchema>;

// verify returns the freshly minted key (shown once) and the MCP URL.
const VerifyResponseSchema = z.object({
  api_key: z.string().min(1),
  mcp_url: z.string().min(1),
});
export type VerifyResponse = z.infer<typeof VerifyResponseSchema>;

/** Error carrying the HTTP status so the page can distinguish expired/invalid. */
export class PodcastApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "PodcastApiError";
  }
}

async function parseErrorMessage(response: Response): Promise<string> {
  const data = await response.json().catch(() => ({} as Record<string, unknown>));
  const detail = (data as Record<string, unknown>).detail;
  const message = (data as Record<string, unknown>).message;
  if (typeof detail === "string") return detail;
  if (typeof message === "string") return message;
  return `HTTP ${response.status}: ${response.statusText}`;
}

export const podcastApi = {
  /**
   * Request a podcast-MCP key. Backend always answers 202 with a generic
   * message (no email enumeration) and sends a verification email.
   */
  async requestKey(email: string, name?: string): Promise<RequestKeyResponse> {
    try {
      const trimmedName = name?.trim();
      const body: { email: string; name?: string } = { email: email.trim() };
      if (trimmedName) body.name = trimmedName;

      const response = await fetch(
        `${API_BASE_URL}${PODCAST_CONSUMER_API_ROUTES.REQUEST_KEY}`,
        {
          method: "POST",
          headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
          body: JSON.stringify(body),
        }
      );

      if (!response.ok) {
        throw new PodcastApiError(response.status, await parseErrorMessage(response));
      }

      const json = await response.json();
      return RequestKeyResponseSchema.parse(json);
    } catch (error) {
      if (error instanceof PodcastApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new PodcastApiError(0, "Unexpected response from the server.");
      }
      throw new PodcastApiError(
        0,
        `Network error: ${error instanceof Error ? error.message : "Unknown error"}`
      );
    }
  },

  /**
   * Exchange a verification token for the one-time API key + MCP URL.
   * A 400/410 means the token is invalid or expired.
   */
  async verify(token: string): Promise<VerifyResponse> {
    try {
      const response = await fetch(
        `${API_BASE_URL}${PODCAST_CONSUMER_API_ROUTES.VERIFY}`,
        {
          method: "POST",
          headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
          body: JSON.stringify({ token }),
        }
      );

      if (!response.ok) {
        throw new PodcastApiError(response.status, await parseErrorMessage(response));
      }

      const json = await response.json();
      return VerifyResponseSchema.parse(json);
    } catch (error) {
      if (error instanceof PodcastApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new PodcastApiError(0, "Unexpected response from the server.");
      }
      throw new PodcastApiError(
        0,
        `Network error: ${error instanceof Error ? error.message : "Unknown error"}`
      );
    }
  },
};
