/**
 * API service for communicating with the FastAPI backend
 * Uses native Fetch API
 */

import {
  API_BASE_URL,
  HEADER_CONTENT_TYPE,
  CONTENT_TYPE_JSON,
  FETCH_CREDENTIALS,
  SESSION_EXPIRED_EVENT,
  AUTH_ROUTES,
  authUserById,
  authUserPassword,
  authUserDisable,
  ERROR_DUPLICATE_EMAIL,
  ACCESS_REQUEST_STATUS_PARAM,
} from "../constants";
import {
  PeriodicNewsletterRequest,
  PeriodicNewsletterResponse,
  DiscussionSelectionResponse,
  DiscussionSelectionsSaveRequest,
  DiscussionSelectionsSaveResponse,
  Phase2GenerationRequest,
  Phase2GenerationResponse,
  RunsListResponse,
  NewsletterContentResponse,
  DiagnosticReport,
  RAGSession,
  RAGSessionDetail,
  RAGSourceStats,
  RAGEvaluation,
  ExtractedImagesResponse,
  ExtractedImagesQuery,
  AccessRequest,
} from "../types";
import { RAG_API_ROUTES } from "../constants/rag";
import {
  AgentMemoryItem,
  AgentSessionSummary,
  CreateSessionRequest,
  CreateSessionResponse,
  RagPreferences,
} from "../types/agent";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// ==================== Admin user management ====================

export interface AdminUser {
  user_id: string;
  email: string;
  role: string;
  communities: string[];
  disabled: boolean;
}

export interface CreateUserPayload {
  email: string;
  password: string;
  role: string;
  communities: string[];
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) {
      // Session missing/expired/tampered mid-session: signal the AuthContext
      // to flip back to the login gate.
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    }
    const errorData = await response.json().catch(() => ({}));
    const errorMessage = errorData.detail || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
    throw new ApiError(response.status, errorMessage);
  }

  try {
    return await response.json();
  } catch (error) {
    throw new ApiError(
      response.status,
      `Invalid JSON response: ${error instanceof Error ? error.message : 'Parse error'}`
    );
  }
}

export const api = {
  /**
   * Generating a periodic newsletter
   */
  async generatePeriodicNewsletter(
    data: PeriodicNewsletterRequest
  ): Promise<PeriodicNewsletterResponse> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 min timeout

    try {
      const response = await fetch(`${API_BASE_URL}/api/generate_periodic_newsletter`, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: {
          [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON,
        },
        body: JSON.stringify(data),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      return handleResponse<PeriodicNewsletterResponse>(response);
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timeout after 10 minutes');
      }
      if (error instanceof ApiError) {
        throw error;
      }
      // Network failure: DNS, timeout, CORS preflight, etc.
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Performing health check
   */
  async healthCheck(): Promise<{ status: string; service: string }> {
    try {
      const response = await fetch(`${API_BASE_URL}/health`, {
        credentials: FETCH_CREDENTIALS,
      });
      return handleResponse(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Phase 2: Loading ranked discussions for HITL selection
   */
  async getDiscussionSelection(runDirectory: string): Promise<DiscussionSelectionResponse> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/discussion_selection/${encodeURIComponent(runDirectory)}`, {
        credentials: FETCH_CREDENTIALS,
      });
      return handleResponse<DiscussionSelectionResponse>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Phase 2: Saving user-selected discussion IDs
   */
  async saveDiscussionSelections(
    data: DiscussionSelectionsSaveRequest
  ): Promise<DiscussionSelectionsSaveResponse> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/save_discussion_selections`, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: {
          [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON,
        },
        body: JSON.stringify(data),
      });
      return handleResponse<DiscussionSelectionsSaveResponse>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Phase 2: Generating newsletter using selected discussions
   */
  async generateNewsletterPhase2(
    data: Phase2GenerationRequest
  ): Promise<Phase2GenerationResponse> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 min timeout

    try {
      const response = await fetch(`${API_BASE_URL}/api/generate_newsletter_phase2`, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: {
          [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON,
        },
        body: JSON.stringify(data),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      return handleResponse<Phase2GenerationResponse>(response);
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timeout after 10 minutes');
      }
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Fetching newsletter file content (HTML, JSON, MD, etc.)
   */
  async getNewsletterFileContent(filePath: string): Promise<{ content: string; file_path: string }> {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/newsletter_file_content?file_path=${encodeURIComponent(filePath)}`,
        { credentials: FETCH_CREDENTIALS }
      );
      return handleResponse<{ content: string; file_path: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Listing all past runs from the output directory
   */
  async listRuns(params?: {
    run_type?: "periodic" | "daily";
    data_source?: string;
    limit?: number;
    offset?: number;
  }): Promise<RunsListResponse> {
    try {
      const queryParams = new URLSearchParams();
      if (params?.run_type) queryParams.set("run_type", params.run_type);
      if (params?.data_source) queryParams.set("data_source", params.data_source);
      if (params?.limit) queryParams.set("limit", params.limit.toString());
      if (params?.offset) queryParams.set("offset", params.offset.toString());

      const url = `${API_BASE_URL}/api/runs${queryParams.toString() ? `?${queryParams.toString()}` : ""}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<RunsListResponse>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Getting newsletter content for a specific run
   */
  async getNewsletterContent(
    runId: string,
    params?: {
      run_type?: "periodic";
      format?: "html" | "md" | "json";
      source?: "consolidated" | "per_chat";
    }
  ): Promise<NewsletterContentResponse> {
    try {
      const queryParams = new URLSearchParams();
      queryParams.set("run_type", params?.run_type || "periodic");
      queryParams.set("format", params?.format || "html");
      queryParams.set("source", params?.source || "consolidated");

      const url = `${API_BASE_URL}/api/runs/${encodeURIComponent(runId)}/newsletter?${queryParams.toString()}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<NewsletterContentResponse>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Getting diagnostic report for a specific run
   */
  async getRunDiagnostics(runId: string): Promise<DiagnosticReport> {
    try {
      const url = `${API_BASE_URL}/api/mongodb/runs/${encodeURIComponent(runId)}/diagnostics`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<DiagnosticReport>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },

  /**
   * Deleting a run and all its associated files
   */
  async deleteRun(runId: string, runType: string = "periodic"): Promise<{ status: string; message: string }> {
    try {
      const queryParams = new URLSearchParams();
      queryParams.set("run_type", runType);

      const url = `${API_BASE_URL}/api/runs/${encodeURIComponent(runId)}?${queryParams.toString()}`;
      const response = await fetch(url, {
        method: "DELETE",
        credentials: FETCH_CREDENTIALS,
      });
      return handleResponse<{ status: string; message: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  },
  // ==================== RAG Conversation ====================

  /**
   * Create a new RAG conversation session
   */
  async createRAGSession(contentSources: string[], title?: string): Promise<RAGSession> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.SESSIONS}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify({ content_sources: contentSources, title }),
      });
      return handleResponse<RAGSession>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * List RAG conversation sessions
   */
  async listRAGSessions(limit: number = 20, skip: number = 0): Promise<RAGSession[]> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.SESSIONS}?limit=${limit}&skip=${skip}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<RAGSession[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Get a RAG session with full message history
   */
  async getRAGSession(sessionId: string): Promise<RAGSessionDetail> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.SESSIONS}/${encodeURIComponent(sessionId)}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<RAGSessionDetail>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Delete a RAG conversation session
   */
  async deleteRAGSession(sessionId: string): Promise<{ message: string }> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.SESSIONS}/${encodeURIComponent(sessionId)}`;
      const response = await fetch(url, { method: "DELETE", credentials: FETCH_CREDENTIALS });
      return handleResponse<{ message: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Scan and ingest podcast audio files from data/podcasts/
   */
  async scanAndIngestPodcasts(forceRefresh: boolean = false): Promise<{ message: string; results: unknown[] }> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.INGEST_PODCASTS_SCAN}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify({ force_refresh: forceRefresh }),
      });
      return handleResponse<{ message: string; results: unknown[] }>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Get chunk counts per content source type
   */
  async getRAGSourceStats(): Promise<RAGSourceStats[]> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.SOURCES_STATS}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<RAGSourceStats[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Get evaluation scores for a session
   */
  async getRAGEvaluations(sessionId: string): Promise<RAGEvaluation[]> {
    try {
      const url = `${API_BASE_URL}${RAG_API_ROUTES.EVALUATIONS}/${encodeURIComponent(sessionId)}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<RAGEvaluation[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  // ==================== Extracted Images Gallery (admin only) ====================

  /**
   * List extracted images for the admin gallery, with optional filters and
   * pagination. Each item carries a ready-to-use image_url for an <img> src.
   */
  async listExtractedImages(query: ExtractedImagesQuery = {}): Promise<ExtractedImagesResponse> {
    try {
      const queryParams = new URLSearchParams();
      if (query.data_source_name) queryParams.set("data_source_name", query.data_source_name);
      if (query.chat_name) queryParams.set("chat_name", query.chat_name);
      if (query.discussion_id) queryParams.set("discussion_id", query.discussion_id);
      if (query.start_date) queryParams.set("start_date", query.start_date);
      if (query.end_date) queryParams.set("end_date", query.end_date);
      if (query.limit !== undefined) queryParams.set("limit", query.limit.toString());
      if (query.offset !== undefined) queryParams.set("offset", query.offset.toString());

      const qs = queryParams.toString();
      const url = `${API_BASE_URL}/api/images${qs ? `?${qs}` : ""}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<ExtractedImagesResponse>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  // ==================== Admin user management ====================

  /**
   * List all accounts (admin only). Never includes password hashes.
   */
  async listUsers(): Promise<AdminUser[]> {
    try {
      const url = `${API_BASE_URL}${AUTH_ROUTES.USERS}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<AdminUser[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Create a new account (admin only). Throws an ApiError carrying the
   * ERROR_DUPLICATE_EMAIL message on a 409 so the UI can surface it inline.
   */
  async createUser(payload: CreateUserPayload): Promise<AdminUser> {
    try {
      const url = `${API_BASE_URL}${AUTH_ROUTES.USERS}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify(payload),
      });
      if (response.status === 409) {
        // Duplicate email: surface a distinguishable, known error code.
        throw new ApiError(409, ERROR_DUPLICATE_EMAIL);
      }
      return handleResponse<AdminUser>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Admin-reset a user's password.
   */
  async resetUserPassword(userId: string, password: string): Promise<{ message?: string }> {
    try {
      const url = `${API_BASE_URL}${authUserPassword(userId)}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify({ password }),
      });
      return handleResponse<{ message?: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Enable or disable a user account.
   */
  async setUserDisabled(userId: string, disabled: boolean): Promise<{ message?: string }> {
    try {
      const url = `${API_BASE_URL}${authUserDisable(userId)}`;
      const response = await fetch(url, {
        method: "POST",
        credentials: FETCH_CREDENTIALS,
        headers: { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON },
        body: JSON.stringify({ disabled }),
      });
      return handleResponse<{ message?: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * List self-signup access requests (admin only). Optionally filter by status;
   * the backend returns newest-first.
   */
  async listAccessRequests(status?: string): Promise<AccessRequest[]> {
    try {
      const queryParams = new URLSearchParams();
      if (status) queryParams.set(ACCESS_REQUEST_STATUS_PARAM, status);
      const qs = queryParams.toString();
      const url = `${API_BASE_URL}${AUTH_ROUTES.ACCESS_REQUESTS}${qs ? `?${qs}` : ""}`;
      const response = await fetch(url, { credentials: FETCH_CREDENTIALS });
      return handleResponse<AccessRequest[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },

  /**
   * Permanently delete a user account.
   */
  async deleteUser(userId: string): Promise<{ message?: string }> {
    try {
      const url = `${API_BASE_URL}${authUserById(userId)}`;
      const response = await fetch(url, {
        method: "DELETE",
        credentials: FETCH_CREDENTIALS,
      });
      return handleResponse<{ message?: string }>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },
};

// ============================================================================
// Agent chat API (v1.14.0+)
// ============================================================================

function _withApiKey(apiKey: string, extra?: HeadersInit): HeadersInit {
  return { ...(extra || {}), "X-API-Key": apiKey };
}

export const agentApi = {
  async createSession(
    apiKey: string,
    payload: CreateSessionRequest = {}
  ): Promise<CreateSessionResponse> {
    const response = await fetch(`${API_BASE_URL}/api/agent/sessions`, {
      method: "POST",
      credentials: FETCH_CREDENTIALS,
      headers: _withApiKey(apiKey, { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON }),
      body: JSON.stringify(payload),
    });
    return handleResponse<CreateSessionResponse>(response);
  },

  async listSessions(apiKey: string): Promise<AgentSessionSummary[]> {
    const response = await fetch(`${API_BASE_URL}/api/agent/sessions`, {
      credentials: FETCH_CREDENTIALS,
      headers: _withApiKey(apiKey),
    });
    return handleResponse<AgentSessionSummary[]>(response);
  },

  async deleteSession(apiKey: string, sessionId: string): Promise<void> {
    const response = await fetch(
      `${API_BASE_URL}/api/agent/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE", credentials: FETCH_CREDENTIALS, headers: _withApiKey(apiKey) }
    );
    if (!response.ok) {
      throw new ApiError(response.status, `HTTP ${response.status}`);
    }
  },

  async listMemories(
    apiKey: string,
    namespace?: string
  ): Promise<AgentMemoryItem[]> {
    const qs = namespace
      ? `?namespace=${encodeURIComponent(namespace)}`
      : "";
    const response = await fetch(`${API_BASE_URL}/api/agent/memories${qs}`, {
      credentials: FETCH_CREDENTIALS,
      headers: _withApiKey(apiKey),
    });
    return handleResponse<AgentMemoryItem[]>(response);
  },

  async deleteMemory(apiKey: string, memoryId: string): Promise<void> {
    const response = await fetch(
      `${API_BASE_URL}/api/agent/memories/${encodeURIComponent(memoryId)}`,
      { method: "DELETE", credentials: FETCH_CREDENTIALS, headers: _withApiKey(apiKey) }
    );
    if (!response.ok) {
      throw new ApiError(response.status, `HTTP ${response.status}`);
    }
  },

  async getRagPreferences(apiKey: string): Promise<RagPreferences> {
    const response = await fetch(`${API_BASE_URL}/api/agent/rag-preferences`, {
      credentials: FETCH_CREDENTIALS,
      headers: _withApiKey(apiKey),
    });
    return handleResponse<RagPreferences>(response);
  },

  async setRagPreferences(
    apiKey: string,
    prefs: RagPreferences
  ): Promise<RagPreferences> {
    const response = await fetch(`${API_BASE_URL}/api/agent/rag-preferences`, {
      method: "PUT",
      credentials: FETCH_CREDENTIALS,
      headers: _withApiKey(apiKey, { [HEADER_CONTENT_TYPE]: CONTENT_TYPE_JSON }),
      body: JSON.stringify(prefs),
    });
    return handleResponse<RagPreferences>(response);
  },
};

export { ApiError };
