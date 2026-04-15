/**
 * API service for communicating with the FastAPI backend
 * Uses native Fetch API
 */

import { API_BASE_URL, HEADER_CONTENT_TYPE, CONTENT_TYPE_JSON } from "../constants";
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
} from "../types";
import { RAG_API_ROUTES } from "../constants/rag";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
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
      const response = await fetch(`${API_BASE_URL}/health`);
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
      const response = await fetch(`${API_BASE_URL}/api/discussion_selection/${encodeURIComponent(runDirectory)}`);
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
        `${API_BASE_URL}/api/newsletter_file_content?file_path=${encodeURIComponent(filePath)}`
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
      const response = await fetch(url);
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
      const response = await fetch(url);
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
      const response = await fetch(url);
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
      const response = await fetch(url);
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
      const response = await fetch(url);
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
      const response = await fetch(url, { method: "DELETE" });
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
      const response = await fetch(url);
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
      const response = await fetch(url);
      return handleResponse<RAGEvaluation[]>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : "Unknown error"}`);
    }
  },
};

export { ApiError };
