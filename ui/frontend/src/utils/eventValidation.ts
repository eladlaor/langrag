/**
 * SSE Event Validation using Zod
 *
 * Provides runtime validation of SSE events received from the backend.
 * Invalid events are logged but don't crash the application.
 */

import { z } from 'zod';
import { ProgressEvent, StageProgressData } from '../types';

// =============================================================================
// ZOD SCHEMAS
// =============================================================================

/**
 * Schema for stage status values
 */
const StageStatusSchema = z.enum(['in_progress', 'completed', 'failed']);

/**
 * Schema for event types
 */
const EventTypeSchema = z.enum([
  'workflow_started',
  'chat_started',
  'stage_progress',
  'chat_completed',
  'chat_failed',
  'consolidation_started',
  'consolidation_completed',
  'hitl_selection_ready',
  'workflow_completed',
  'error',
]);

/**
 * Schema for stage_progress event data
 */
const StageProgressDataSchema = z.object({
  chat_name: z.string(),
  stage: z.string(),
  status: StageStatusSchema,
  message: z.string(),
  output_file: z.string().optional(),
  metadata: z.record(z.unknown()).optional(),
});

/**
 * Schema for workflow_started event data
 */
const WorkflowStartedDataSchema = z.object({
  chat_names: z.array(z.string()).optional(),
  output_directory: z.string().optional(),
  consolidate_chats: z.boolean().optional(),
});

/**
 * Schema for workflow_completed event data
 */
const WorkflowCompletedDataSchema = z.object({
  successful_chats: z.number().optional(),
  failed_chats: z.number().optional(),
  consolidated_output_dir: z.string().optional(),
  results: z.unknown().optional(),
});

/**
 * Schema for consolidation_started event data
 */
const ConsolidationStartedDataSchema = z.object({
  message: z.string().optional(),
});

/**
 * Schema for consolidation_completed event data
 */
const ConsolidationCompletedDataSchema = z.object({
  output_dir: z.string().optional(),
  consolidated_output_dir: z.string().optional(),
});

/**
 * Schema for hitl_selection_ready event data
 */
const HitlSelectionReadyDataSchema = z.object({
  run_directory: z.string(),
  timeout_deadline: z.string().optional(),
});

/**
 * Schema for error event data
 */
const ErrorDataSchema = z.object({
  message: z.string().optional(),
  error: z.string().optional(),
  code: z.string().optional(),
});

/**
 * Base progress event schema
 */
const BaseProgressEventSchema = z.object({
  event_type: EventTypeSchema,
  timestamp: z.string(),
  data: z.unknown(),
});

// =============================================================================
// VALIDATION FUNCTIONS
// =============================================================================

/**
 * Validation result type
 */
export interface ValidationResult<T> {
  success: boolean;
  data?: T;
  error?: string;
}

/**
 * Validate a raw SSE event object
 *
 * @param raw - Raw parsed JSON from SSE stream
 * @returns Validated ProgressEvent or null if invalid
 */
export function validateEvent(raw: unknown): ProgressEvent | null {
  try {
    // First validate the base structure
    const baseResult = BaseProgressEventSchema.safeParse(raw);
    if (!baseResult.success) {
      console.warn('[SSE Validation] Invalid event structure:', baseResult.error.message);
      return null;
    }

    const event = baseResult.data;

    // Then validate event-specific data based on event_type
    let dataValidation: z.SafeParseReturnType<unknown, unknown>;

    switch (event.event_type) {
      case 'workflow_started':
        dataValidation = WorkflowStartedDataSchema.safeParse(event.data);
        break;
      case 'stage_progress':
        dataValidation = StageProgressDataSchema.safeParse(event.data);
        break;
      case 'workflow_completed':
        dataValidation = WorkflowCompletedDataSchema.safeParse(event.data);
        break;
      case 'consolidation_started':
        dataValidation = ConsolidationStartedDataSchema.safeParse(event.data);
        break;
      case 'consolidation_completed':
        dataValidation = ConsolidationCompletedDataSchema.safeParse(event.data);
        break;
      case 'hitl_selection_ready':
        dataValidation = HitlSelectionReadyDataSchema.safeParse(event.data);
        break;
      case 'error':
        dataValidation = ErrorDataSchema.safeParse(event.data);
        break;
      default:
        // For unknown event types, accept any data (backward compatibility)
        dataValidation = { success: true, data: event.data };
    }

    if (!dataValidation.success) {
      console.warn(
        `[SSE Validation] Invalid data for event type '${event.event_type}':`,
        (dataValidation as any).error?.message || 'Unknown error'
      );
      // Still return the event with original data for graceful degradation
      return {
        event_type: event.event_type,
        timestamp: event.timestamp,
        data: event.data as any,
      };
    }

    return {
      event_type: event.event_type,
      timestamp: event.timestamp,
      data: dataValidation.data as any,
    };
  } catch (err) {
    console.error('[SSE Validation] Unexpected validation error:', err);
    return null;
  }
}

/**
 * Validate stage progress data specifically
 *
 * @param data - Raw stage progress data
 * @returns Validated StageProgressData or null
 */
export function validateStageProgressData(data: unknown): StageProgressData | null {
  const result = StageProgressDataSchema.safeParse(data);
  if (!result.success) {
    console.warn('[SSE Validation] Invalid stage progress data:', result.error.message);
    return null;
  }
  return result.data;
}

/**
 * Check if an event type is a known/expected type
 *
 * @param eventType - Event type string to check
 * @returns True if event type is known
 */
export function isKnownEventType(eventType: string): boolean {
  return EventTypeSchema.safeParse(eventType).success;
}
