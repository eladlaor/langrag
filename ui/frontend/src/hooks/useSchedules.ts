/**
 * React hook for managing scheduled newsletters via API
 *
 * Provides CRUD operations for newsletter schedules.
 *
 * Usage:
 * ```tsx
 * const { schedules, loading, error, createSchedule, deleteSchedule, toggleSchedule, refresh } = useSchedules();
 * ```
 */

import { useState, useCallback, useEffect } from 'react';
import { API_BASE_URL } from '../constants';

// Schedule types
export interface Schedule {
  id: string;
  name: string;
  interval_days: number;
  run_time: string;
  data_source_name: string;
  whatsapp_chat_names_to_include: string[];
  email_recipients: string[];
  desired_language_for_summary: string;
  summary_format: string;
  consolidate_chats: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_run: string | null;
  last_run_status: string | null;
  next_run: string;
  run_count: number;
}

export interface CreateScheduleRequest {
  name: string;
  interval_days: number;
  run_time: string;
  data_source_name: string;
  whatsapp_chat_names_to_include: string[];
  email_recipients: string[];
  desired_language_for_summary?: string;
  summary_format?: string;
  consolidate_chats?: boolean;
  enabled?: boolean;
}

export interface UpdateScheduleRequest {
  name?: string;
  interval_days?: number;
  run_time?: string;
  data_source_name?: string;
  whatsapp_chat_names_to_include?: string[];
  email_recipients?: string[];
  desired_language_for_summary?: string;
  summary_format?: string;
  consolidate_chats?: boolean;
  enabled?: boolean;
}

interface UseSchedulesState {
  schedules: Schedule[];
  loading: boolean;
  error: string | null;
}

export function useSchedules() {
  const [state, setState] = useState<UseSchedulesState>({
    schedules: [],
    loading: false,
    error: null,
  });

  /**
   * Fetch all schedules
   */
  const fetchSchedules = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}/api/schedules`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      setState({
        schedules: data.schedules || [],
        loading: false,
        error: null,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch schedules';
      console.error('[useSchedules] Fetch error:', errorMessage);
      setState((prev) => ({
        ...prev,
        loading: false,
        error: errorMessage,
      }));
    }
  }, []);

  /**
   * Create a new schedule
   */
  const createSchedule = useCallback(async (request: CreateScheduleRequest): Promise<boolean> => {
    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}/api/schedules`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      // Refresh the list
      await fetchSchedules();
      return true;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create schedule';
      console.error('[useSchedules] Create error:', errorMessage);
      setState((prev) => ({
        ...prev,
        loading: false,
        error: errorMessage,
      }));
      return false;
    }
  }, [fetchSchedules]);

  /**
   * Update an existing schedule
   */
  const updateSchedule = useCallback(
    async (scheduleId: string, request: UpdateScheduleRequest): Promise<boolean> => {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(request),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
        }

        // Refresh the list
        await fetchSchedules();
        return true;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to update schedule';
        console.error('[useSchedules] Update error:', errorMessage);
        setState((prev) => ({
          ...prev,
          loading: false,
          error: errorMessage,
        }));
        return false;
      }
    },
    [fetchSchedules]
  );

  /**
   * Delete a schedule
   */
  const deleteSchedule = useCallback(
    async (scheduleId: string): Promise<boolean> => {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}`, {
          method: 'DELETE',
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
        }

        // Refresh the list
        await fetchSchedules();
        return true;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to delete schedule';
        console.error('[useSchedules] Delete error:', errorMessage);
        setState((prev) => ({
          ...prev,
          loading: false,
          error: errorMessage,
        }));
        return false;
      }
    },
    [fetchSchedules]
  );

  /**
   * Toggle schedule enabled/disabled
   */
  const toggleSchedule = useCallback(
    async (scheduleId: string): Promise<boolean> => {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const response = await fetch(`${API_BASE_URL}/api/schedules/${scheduleId}/toggle`, {
          method: 'PATCH',
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
        }

        // Refresh the list
        await fetchSchedules();
        return true;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to toggle schedule';
        console.error('[useSchedules] Toggle error:', errorMessage);
        setState((prev) => ({
          ...prev,
          loading: false,
          error: errorMessage,
        }));
        return false;
      }
    },
    [fetchSchedules]
  );

  // Fetch schedules on mount
  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  return {
    schedules: state.schedules,
    loading: state.loading,
    error: state.error,
    createSchedule,
    updateSchedule,
    deleteSchedule,
    toggleSchedule,
    refresh: fetchSchedules,
  };
}
