/**
 * React hook for streaming newsletter generation progress via SSE
 *
 * This hook manages an EventSource connection to the backend streaming endpoint,
 * processes incoming progress events, and maintains real-time state for the UI.
 *
 * Features:
 * - Exponential backoff reconnection (max 3 attempts)
 * - Proper SSE message boundary parsing
 * - Connection timeout detection (30s without events)
 * - Consolidation progress tracking
 *
 * Usage:
 * ```tsx
 * const { state, start, cancel } = useNewsletterStream();
 *
 * // Start generation
 * start(requestData);
 *
 * // Render progress
 * if (state.status === 'running') {
 *   return <ProgressTracker chats={state.chats} />;
 * }
 * ```
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import {
  PeriodicNewsletterRequest,
  PeriodicNewsletterResponse,
  ProgressState,
  ProgressEvent,
  StageProgressData,
  ChatProgress,
  ConsolidationProgress,
} from '../types';
import { API_BASE_URL } from '../constants';
import { validateEvent } from '../utils/eventValidation';

// Per-chat pipeline stages
const PIPELINE_STAGES = [
  'extract_messages',
  'preprocess_messages',
  'translate_messages',
  'separate_discussions',
  'rank_discussions',
  'generate_content',
  'enrich_with_links',
  'translate_final_summary',
];

// Consolidation stages (used when consolidate_chats=true)
const CONSOLIDATION_STAGES = [
  'setup_consolidated_directories',
  'consolidate_discussions',
  'rank_consolidated_discussions',
  'generate_consolidated_newsletter',
  'enrich_consolidated_newsletter',
  'translate_consolidated_newsletter',
];

// Special chat name for consolidation events
const CONSOLIDATION_CHAT_NAME = '__consolidated__';

// SSE reconnection constants
const MAX_RECONNECT_ATTEMPTS = 3;
const INITIAL_RECONNECT_DELAY_MS = 2000;
const CONNECTION_TIMEOUT_MS = 30000; // 30s - backend sends keepalive every 15s

/**
 * Parse SSE message buffer into complete messages
 * SSE messages are separated by double newlines (\n\n)
 */
function parseSSEMessages(buffer: string): { messages: string[]; remaining: string } {
  const messages: string[] = [];
  let remaining = buffer;

  // Split on double newline (SSE message boundary)
  const parts = remaining.split('\n\n');

  // All but the last part are complete messages
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i].trim();
    if (part) {
      messages.push(part);
    }
  }

  // Last part may be incomplete (no trailing \n\n yet)
  remaining = parts[parts.length - 1];

  return { messages, remaining };
}

export function useNewsletterStream() {
  const [state, setState] = useState<ProgressState>({
    status: 'idle',
    chats: new Map(),
    totalChats: 0,
    completedChats: 0,
    failedChats: 0,
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const requestDataRef = useRef<PeriodicNewsletterRequest | null>(null);

  // Reconnection state
  const reconnectAttemptRef = useRef<number>(0);
  const lastEventTimeRef = useRef<number>(Date.now());
  const timeoutCheckIntervalRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Initializing chat progress tracking
   */
  const initializeChats = useCallback((chatNames: string[]) => {
    const chatsMap = new Map<string, ChatProgress>();

    chatNames.forEach((name) => {
      chatsMap.set(name, {
        name,
        status: 'pending',
        currentStage: '',
        currentMessage: 'Waiting...',
        completedStages: [],
        outputPaths: {},
      });
    });

    return chatsMap;
  }, []);

  /**
   * Handling workflow_started event
   */
  const handleWorkflowStarted = useCallback((data: any) => {
    const chatNames = data.chat_names || [];
    const chatsMap = initializeChats(chatNames);

    setState((prev) => ({
      ...prev,
      status: 'running',
      chats: chatsMap,
      totalChats: chatNames.length,
      outputDirectory: data.output_directory,
    }));
  }, [initializeChats]);

  /**
   * Handling stage_progress event
   * Supports both per-chat progress and consolidation progress
   */
  const handleStageProgress = useCallback((data: StageProgressData) => {
    // Check if this is a consolidation event
    if (data.chat_name === CONSOLIDATION_CHAT_NAME) {
      setState((prev) => {
        // Initialize consolidation progress if needed
        const consolidation: ConsolidationProgress = prev.consolidation || {
          status: 'pending',
          currentStage: '',
          currentMessage: 'Waiting...',
          completedStages: [],
          outputPaths: {},
        };

        if (data.status === 'in_progress') {
          consolidation.status = 'in_progress';
          consolidation.currentStage = data.stage;
          consolidation.currentMessage = data.message;
        } else if (data.status === 'completed') {
          if (!consolidation.completedStages.includes(data.stage)) {
            consolidation.completedStages.push(data.stage);
          }
          consolidation.currentMessage = data.message;

          // Store output file path
          if (data.output_file) {
            consolidation.outputPaths[data.stage] = data.output_file;
          }

          // Check if all consolidation stages completed
          if (consolidation.completedStages.length === CONSOLIDATION_STAGES.length) {
            consolidation.status = 'completed';
            consolidation.currentStage = '';
            consolidation.currentMessage = 'Consolidation completed';
          }
        } else if (data.status === 'failed') {
          consolidation.status = 'failed';
          consolidation.currentMessage = data.message;
          consolidation.error = data.message;
        }

        return { ...prev, consolidation };
      });
      return;
    }

    // Regular per-chat progress handling
    setState((prev) => {
      const newChats = new Map(prev.chats);
      const chat = newChats.get(data.chat_name);

      if (!chat) return prev;

      // Updating chat status
      if (data.status === 'in_progress') {
        chat.status = 'in_progress';
        chat.currentStage = data.stage;
        chat.currentMessage = data.message;
      } else if (data.status === 'completed') {
        if (!chat.completedStages.includes(data.stage)) {
          chat.completedStages.push(data.stage);
        }
        chat.currentMessage = data.message;

        // Storing output file path
        if (data.output_file) {
          chat.outputPaths[data.stage] = data.output_file;
        }

        // Checking if all stages completed
        if (chat.completedStages.length === PIPELINE_STAGES.length) {
          chat.status = 'completed';
          chat.currentStage = '';
          chat.currentMessage = 'Completed';
        }
      } else if (data.status === 'failed') {
        chat.status = 'failed';
        chat.failedStage = data.stage;
        chat.currentMessage = data.message;
        chat.error = data.message;
      }

      // Storing metadata
      if (data.metadata) {
        chat.metadata = { ...chat.metadata, ...data.metadata };
      }

      newChats.set(data.chat_name, chat);
      return { ...prev, chats: newChats };
    });
  }, []);

  /**
   * Handling workflow_completed event
   */
  const handleWorkflowCompleted = useCallback((data: any) => {
    setState((prev) => ({
      ...prev,
      status: 'completed',
      completedChats: data.successful_chats || 0,
      failedChats: data.failed_chats || 0,
      consolidatedOutputDir: data.consolidated_output_dir,
      result: data.results as PeriodicNewsletterResponse,
    }));

    // Closing event source
    if (eventSourceRef.current) {
      if ('abort' in eventSourceRef.current) {
        (eventSourceRef.current as any).abort();
      } else if ('close' in eventSourceRef.current) {
        (eventSourceRef.current as EventSource).close();
      }
      eventSourceRef.current = null;
    }
  }, []);

  /**
   * Handling error event
   */
  const handleError = useCallback((data: any) => {
    setState((prev) => ({
      ...prev,
      status: 'error',
      error: data.message || 'An error occurred during newsletter generation',
    }));

    // Closing event source
    if (eventSourceRef.current) {
      if ('abort' in eventSourceRef.current) {
        (eventSourceRef.current as any).abort();
      } else if ('close' in eventSourceRef.current) {
        (eventSourceRef.current as EventSource).close();
      }
      eventSourceRef.current = null;
    }
  }, []);

  /**
   * Handling hitl_selection_ready event - Phase 1 complete, waiting for user selection
   */
  const handleHitlSelectionReady = useCallback((data: any) => {
    setState((prev) => ({
      ...prev,
      status: 'hitl_selection',
      hitlEnabled: true,
      hitlRunDirectory: data.run_directory,
      hitlSelectionDeadline: data.timeout_deadline,
    }));

    // Closing event source - workflow paused for human input
    if (eventSourceRef.current) {
      if ('abort' in eventSourceRef.current) {
        (eventSourceRef.current as any).abort();
      } else if ('close' in eventSourceRef.current) {
        (eventSourceRef.current as EventSource).close();
      }
      eventSourceRef.current = null;
    }
  }, []);

  /**
   * Handling consolidation_started event
   */
  const handleConsolidationStarted = useCallback((data: any) => {
    console.log('[SSE] Consolidation started');
    setState((prev) => ({
      ...prev,
      consolidation: {
        status: 'in_progress',
        currentStage: '',
        currentMessage: 'Starting consolidation...',
        completedStages: [],
        outputPaths: {},
      },
    }));
  }, []);

  /**
   * Handling consolidation_completed event
   */
  const handleConsolidationCompleted = useCallback((data: any) => {
    console.log('[SSE] Consolidation completed');
    setState((prev) => ({
      ...prev,
      consolidation: prev.consolidation
        ? {
            ...prev.consolidation,
            status: 'completed',
            currentMessage: 'Consolidation completed',
          }
        : undefined,
      consolidatedOutputDir: data.output_dir || data.consolidated_output_dir,
    }));
  }, []);

  /**
   * Processing incoming SSE event
   */
  const processEvent = useCallback(
    (event: ProgressEvent) => {
      console.log('[SSE Event]', event.event_type, event.data);

      // Update last event time for timeout detection
      lastEventTimeRef.current = Date.now();

      switch (event.event_type) {
        case 'workflow_started':
          handleWorkflowStarted(event.data);
          break;
        case 'stage_progress':
          handleStageProgress(event.data as StageProgressData);
          break;
        case 'consolidation_started':
          handleConsolidationStarted(event.data);
          break;
        case 'consolidation_completed':
          handleConsolidationCompleted(event.data);
          break;
        case 'workflow_completed':
          handleWorkflowCompleted(event.data);
          break;
        case 'hitl_selection_ready':
          handleHitlSelectionReady(event.data);
          break;
        case 'error':
          handleError(event.data);
          break;
        // Handling other event types as needed
        default:
          console.log('[SSE] Unknown event type:', event.event_type);
      }
    },
    [handleWorkflowStarted, handleStageProgress, handleConsolidationStarted, handleConsolidationCompleted, handleWorkflowCompleted, handleHitlSelectionReady, handleError]
  );

  /**
   * Clear timeout check interval
   */
  const clearTimeoutCheck = useCallback(() => {
    if (timeoutCheckIntervalRef.current) {
      clearInterval(timeoutCheckIntervalRef.current);
      timeoutCheckIntervalRef.current = null;
    }
  }, []);

  /**
   * Start timeout check interval
   * Triggers reconnection if no events received for CONNECTION_TIMEOUT_MS
   */
  const startTimeoutCheck = useCallback((attemptReconnect: () => void) => {
    clearTimeoutCheck();
    timeoutCheckIntervalRef.current = setInterval(() => {
      const timeSinceLastEvent = Date.now() - lastEventTimeRef.current;
      if (timeSinceLastEvent > CONNECTION_TIMEOUT_MS) {
        console.warn(`[SSE] Connection timeout (${CONNECTION_TIMEOUT_MS}ms without events)`);
        attemptReconnect();
      }
    }, 5000); // Check every 5 seconds
  }, [clearTimeoutCheck]);

  /**
   * Starting newsletter generation with SSE streaming
   * Includes reconnection logic with exponential backoff
   */
  const start = useCallback((requestData: PeriodicNewsletterRequest) => {
    // Closing existing connection if any
    if (eventSourceRef.current) {
      if ('abort' in eventSourceRef.current) {
        (eventSourceRef.current as any).abort();
      }
    }

    // Clear any existing timeout check
    clearTimeoutCheck();

    // Storing request data
    requestDataRef.current = requestData;

    // Reset reconnection state
    reconnectAttemptRef.current = 0;
    lastEventTimeRef.current = Date.now();

    // Resetting state
    setState({
      status: 'connecting',
      chats: new Map(),
      totalChats: 0,
      completedChats: 0,
      failedChats: 0,
    });

    // Creating SSE connection
    const url = `${API_BASE_URL}/api/generate_periodic_newsletter/stream`;

    // We need to use POST, but EventSource only supports GET
    // So we use fetch with streaming response instead
    const controller = new AbortController();

    const attemptConnection = async () => {
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestData),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('Response body is not readable');
        }

        // Connection successful - reset reconnection counter
        reconnectAttemptRef.current = 0;
        lastEventTimeRef.current = Date.now();

        const decoder = new TextDecoder();
        let buffer = '';

        // Reading stream
        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          // Update last event time (includes keepalives)
          lastEventTimeRef.current = Date.now();

          // Decoding chunk
          buffer += decoder.decode(value, { stream: true });

          // Parse complete SSE messages using proper boundary detection
          const { messages, remaining } = parseSSEMessages(buffer);
          buffer = remaining;

          for (const message of messages) {
            // Process each line in the message
            const lines = message.split('\n');
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const jsonData = line.slice(6); // Remove 'data: ' prefix
                  const rawEvent = JSON.parse(jsonData);

                  // Validate event structure using Zod
                  const event = validateEvent(rawEvent);
                  if (event) {
                    processEvent(event);
                  } else {
                    console.warn('[SSE] Skipping invalid event:', rawEvent);
                  }
                } catch (err) {
                  console.error('[SSE] Failed to parse event:', line, err);
                }
              }
              // Ignoring keepalive comments (lines starting with ':')
            }
          }
        }
      } catch (err: any) {
        if (err.name === 'AbortError') {
          console.log('[SSE] Connection cancelled by user');
          clearTimeoutCheck();
          setState((prev) => ({ ...prev, status: 'idle' }));
          return;
        }

        console.error('[SSE] Connection error:', err);

        // Attempt reconnection with exponential backoff
        reconnectAttemptRef.current++;
        if (reconnectAttemptRef.current <= MAX_RECONNECT_ATTEMPTS) {
          const delay = INITIAL_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptRef.current - 1);
          console.log(`[SSE] Reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`);

          setState((prev) => ({
            ...prev,
            status: 'reconnecting',
          }));

          setTimeout(() => {
            if (!controller.signal.aborted) {
              attemptConnection();
            }
          }, delay);
        } else {
          // Max reconnection attempts reached
          console.error('[SSE] Max reconnection attempts reached');
          clearTimeoutCheck();
          setState({
            status: 'error',
            chats: new Map(),
            totalChats: 0,
            completedChats: 0,
            failedChats: 0,
            error: `Connection lost after ${MAX_RECONNECT_ATTEMPTS} reconnection attempts: ${err.message}`,
          });
        }
      }
    };

    // Define reconnect handler for timeout detection
    const handleTimeoutReconnect = () => {
      reconnectAttemptRef.current++;
      if (reconnectAttemptRef.current <= MAX_RECONNECT_ATTEMPTS) {
        console.log(`[SSE] Timeout reconnection (attempt ${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
        setState((prev) => ({
          ...prev,
          status: 'reconnecting',
        }));
        attemptConnection();
      } else {
        clearTimeoutCheck();
        setState((prev) => ({
          ...prev,
          status: 'error',
          error: 'Connection timeout: no events received for 30 seconds',
        }));
      }
    };

    // Start timeout detection
    startTimeoutCheck(handleTimeoutReconnect);

    // Start initial connection
    attemptConnection();

    // Storing abort controller for cancellation
    (eventSourceRef as any).current = {
      abort: () => {
        clearTimeoutCheck();
        controller.abort();
      }
    };
  }, [processEvent, clearTimeoutCheck, startTimeoutCheck]);

  /**
   * Cancelling ongoing generation
   */
  const cancel = useCallback(() => {
    // Clear timeout check
    clearTimeoutCheck();

    if (eventSourceRef.current) {
      if ('abort' in eventSourceRef.current) {
        (eventSourceRef.current as any).abort();
      } else if ('close' in eventSourceRef.current) {
        (eventSourceRef.current as EventSource).close();
      }
      eventSourceRef.current = null;
    }

    // Reset reconnection state
    reconnectAttemptRef.current = 0;

    setState((prev) => ({
      ...prev,
      status: 'idle',
    }));
  }, [clearTimeoutCheck]);

  /**
   * Cleaning up on unmount
   */
  useEffect(() => {
    return () => {
      // Clear timeout check interval
      if (timeoutCheckIntervalRef.current) {
        clearInterval(timeoutCheckIntervalRef.current);
      }

      if (eventSourceRef.current) {
        if ('abort' in eventSourceRef.current) {
          (eventSourceRef.current as any).abort();
        } else if ('close' in eventSourceRef.current) {
          (eventSourceRef.current as EventSource).close();
        }
      }
    };
  }, []);

  return {
    state,
    start,
    cancel,
  };
}
