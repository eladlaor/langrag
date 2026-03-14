/**
 * Constants for the LangRAG UI
 * Matches the backend configuration from constants.py
 */

// Community structure with grouped chats
export const COMMUNITY_STRUCTURE = {
  langtalks: {
    "LangTalks Community": [
      "LangTalks Community",
      "LangTalks Community 2",
      "LangTalks Community 3",
      "LangTalks Community 4",
      "LangTalks - Code Generation Agents",
      "LangTalks AI-SDLC",
      "LangTalks - English",
      "LangTalks - AI driven coding",
    ],
  },
  mcp_israel: {
    "MCP Israel": [
      "MCP Israel",
      "MCP Israel #2",
      "A2A Israel",
      "MCP-UI",
    ],
  },
  n8n_israel: {
    "n8n Israel": [
      "n8n israel - Main 1",
      "n8n israel - Main 2",
      "n8n Israel - Main 3",
    ],
  },
  ai_transformation_guild: {
    "AI Transformation Guild": [
      "AI Transformation Guild",
    ],
  },
  ail: {
    "AIL - AI Leaders Community": [
      "AIL - AI Leaders Community",
    ],
  },
} as const;

// Flattened version for backward compatibility
export const KNOWN_WHATSAPP_CHAT_NAMES = Object.fromEntries(
  Object.entries(COMMUNITY_STRUCTURE).map(([communityKey, communityGroups]) => [
    communityKey,
    Object.values(communityGroups).flat(),
  ])
);

export const DATA_SOURCES = [
  { value: "langtalks", label: "LangTalks" },
  { value: "mcp_israel", label: "MCP Israel" },
  { value: "n8n_israel", label: "n8n Israel" },
  { value: "ai_transformation_guild", label: "AI Transformation Guild" },
  { value: "ail", label: "AIL - AI Leaders Community" },
] as const;

export const SUMMARY_FORMATS = [
  { value: "langtalks_format", label: "LangTalks Format" },
  { value: "mcp_israel_format", label: "MCP Israel Format" },
  { value: "whatsapp_format", label: "WhatsApp Format" },
] as const;

export const LANGUAGES = [
  { value: "english", label: "English" },
  { value: "hebrew", label: "Hebrew" },
  { value: "spanish", label: "Spanish" },
  { value: "french", label: "French" },
] as const;

export const OUTPUT_ACTIONS = [
  { value: "save_local", label: "Save Locally" },
  { value: "webhook", label: "Trigger Webhook" },
  { value: "send_email", label: "Send Email" },
  { value: "send_substack", label: "Post to Substack (Coming Soon)" },
  { value: "send_linkedin", label: "Create LinkedIn Draft" },
] as const;

// Universal output actions allowed for all communities
export const UNIVERSAL_OUTPUT_ACTIONS = [
  "save_local",
  "webhook",
  "send_email",
];

// Community-specific publishing platform actions (mirrors backend COMMUNITY_ALLOWED_OUTPUT_ACTIONS)
export const COMMUNITY_ALLOWED_OUTPUT_ACTIONS: Record<string, string[]> = {
  langtalks: ["send_substack"],
  mcp_israel: ["send_linkedin"],
  n8n_israel: [],
  ai_transformation_guild: [],
  ail: [],
};

export const FORCE_REFRESH_OPTIONS = [
  { key: "force_refresh_extraction", label: "Extract Messages" },
  { key: "force_refresh_preprocessing", label: "Preprocess Messages" },
  { key: "force_refresh_translation", label: "Translate Messages" },
  { key: "force_refresh_separate_discussions", label: "Separate Discussions" },
  { key: "force_refresh_content", label: "Generate Content" },
  { key: "force_refresh_final_translation", label: "Final Translation" },
] as const;

export const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || "";

// HTTP Constants
export const HEADER_CONTENT_TYPE = "Content-Type";
export const CONTENT_TYPE_JSON = "application/json";
