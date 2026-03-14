/**
 * TypeScript type definitions matching FastAPI Pydantic models
 */

// Request types
export interface PeriodicNewsletterRequest {
  start_date: string; // YYYY-MM-DD format
  end_date: string; // YYYY-MM-DD format
  data_source_name: "langtalks" | "mcp_israel" | "n8n_israel" | "ai_transformation_guild";
  whatsapp_chat_names_to_include: string[];
  desired_language_for_summary: string;
  summary_format: "langtalks_format" | "mcp_israel_format";

  // Optional force refresh flags
  force_refresh_extraction?: boolean;
  force_refresh_preprocessing?: boolean;
  force_refresh_translation?: boolean;
  force_refresh_separate_discussions?: boolean;
  force_refresh_content?: boolean;
  force_refresh_final_translation?: boolean;

  // Optional output configuration
  output_actions?: string[];
  webhook_url?: string;
  email_recipients?: string[];
  substack_blog_id?: string;
  output_dir?: string;

  // HITL (Human-in-the-Loop) configuration
  hitl_selection_timeout_minutes?: number; // 0 = disabled (automatic), >0 = enabled with timeout
}

// Response types
export interface NewsletterResult {
  date?: string;
  chat_name: string;
  success: boolean;
  newsletter_json?: string;
  newsletter_md?: string;
  translated_file?: string;
  error?: string;
  message_count?: number;
  reused_existing?: boolean;
}

export interface PeriodicNewsletterResponse {
  message: string;
  total_chats: number;
  successful_chats: number;
  failed_chats: number;
  results: NewsletterResult[];
}

// Form data types
export interface ForceRefreshFlags {
  force_refresh_extraction: boolean;
  force_refresh_preprocessing: boolean;
  force_refresh_translation: boolean;
  force_refresh_separate_discussions: boolean;
  force_refresh_content: boolean;
  force_refresh_final_translation: boolean;
}

export interface OutputConfiguration {
  output_actions: string[];
  webhook_url: string;
  email_recipients: string;
  substack_blog_id: string;
}

export interface HITLConfiguration {
  enabled: boolean;
  timeoutMinutes: number; // User-friendly timeout (15, 30, 60, 120, etc.)
}

// Progress tracking types for SSE streaming
export type ProgressEventType =
  | "workflow_started"
  | "chat_started"
  | "stage_progress"
  | "chat_completed"
  | "chat_failed"
  | "consolidation_started"
  | "consolidation_completed"
  | "hitl_selection_ready"  // Phase 1 complete, waiting for user selection
  | "workflow_completed"
  | "error";

export type StageStatus = "in_progress" | "completed" | "failed";

export type ChatStatus = "pending" | "in_progress" | "completed" | "failed";

export type WorkflowStatus = "idle" | "connecting" | "reconnecting" | "running" | "hitl_selection" | "completed" | "error";

export interface ProgressEvent {
  event_type: ProgressEventType;
  timestamp: string;
  data: any;
}

export interface StageProgressData {
  chat_name: string;
  stage: string;
  status: StageStatus;
  message: string;
  output_file?: string;
  metadata?: Record<string, any>;
}

export interface ChatProgress {
  name: string;
  status: ChatStatus;
  currentStage: string;
  currentMessage: string;
  completedStages: string[];
  failedStage?: string;
  outputPaths: Record<string, string>;
  error?: string;
  metadata?: Record<string, any>;
}

/**
 * Progress tracking for cross-chat consolidation phase
 */
export interface ConsolidationProgress {
  status: ChatStatus;
  currentStage: string;
  currentMessage: string;
  completedStages: string[];
  outputPaths: Record<string, string>;
  error?: string;
}

export interface ProgressState {
  status: WorkflowStatus;
  chats: Map<string, ChatProgress>;
  outputDirectory?: string;
  consolidatedOutputDir?: string;
  totalChats: number;
  completedChats: number;
  failedChats: number;
  error?: string;
  result?: PeriodicNewsletterResponse;
  // HITL fields
  hitlEnabled?: boolean;
  hitlRunDirectory?: string;  // Path to output dir for Phase 2 operations
  hitlSelectionDeadline?: string;  // ISO timestamp when selection expires
  // Consolidation progress (visible when consolidate_chats=true)
  consolidation?: ConsolidationProgress;
}

// Phase 2 HITL Types
export interface DiscussionSource {
  group: string;
  first_message_timestamp: number;
}

export interface RankedDiscussionItem {
  id: string;
  rank: number;
  title: string;
  group_name: string; // For standalone discussions
  first_message_date: string; // DD.MM.YY
  first_message_time: string; // HH:MM
  num_messages: number;
  num_unique_participants: number;
  nutshell: string;
  relevance_score?: number; // 0-10
  reasoning: string;

  // NEW: Merged discussion metadata
  is_merged?: boolean;
  source_discussions?: DiscussionSource[];
  source_groups?: string[]; // List of group names for easy display
}

export interface DiscussionSelectionResponse {
  discussions: RankedDiscussionItem[];
  timeout_deadline: string; // ISO timestamp
  total_discussions: number;
  format_type: string;
}

export interface DiscussionSelectionsSaveRequest {
  run_directory: string;
  selected_discussion_ids: string[];
}

export interface DiscussionSelectionsSaveResponse {
  message: string;
  selections_file_path: string;
  num_selected: number;
}

export interface Phase2GenerationRequest {
  run_directory: string;
}

export interface Phase2GenerationResponse {
  message: string;
  newsletter_path: string;
  num_discussions: number;
  content_length: number;
  validation_passed: boolean;

  // Base newsletter paths
  base_json_path?: string;
  base_md_path?: string;
  base_html_path?: string;

  // Enriched newsletter paths (with links)
  enriched_json_path?: string;
  enriched_md_path?: string;
  enriched_html_path?: string;

  // Link metadata
  links_metadata_path?: string;
}

// Runs Browser Types
export interface RunInfo {
  run_id: string;
  run_type: "periodic";
  data_source: string;
  start_date: string;
  end_date: string;
  created_at?: string;
  has_consolidated: boolean;
  has_per_chat: boolean;
  has_hitl_pending: boolean;
  newsletter_paths: Record<string, string>;
}

export interface RunsListResponse {
  total: number;
  runs: RunInfo[];
}

export interface NewsletterContentResponse {
  run_id: string;
  content_html?: string;
  content_md?: string;
  content_json?: string;
  direction: "rtl" | "ltr";
  title?: string;
  file_path?: string;
}

// Diagnostics Types
export interface DiagnosticIssue {
  severity: "critical" | "warning" | "info";
  category: string;
  message: string;
  node?: string;
  timestamp: string;
  details: Record<string, any>;
}

export interface DiagnosticReport {
  run_id: string;
  status: "clean" | "issues_found";
  total_issues?: number;
  by_severity?: {
    critical: number;
    warning: number;
    info: number;
  };
  report?: {
    executive_summary: string;
    issues_by_priority: DiagnosticIssue[];
    actionable_recommendations: string[];
    patterns_detected: string[];
  };
  raw_issues?: DiagnosticIssue[];
  generated_at?: string;
}
