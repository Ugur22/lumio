// Mirrors models.py. Datetimes arrive as ISO-8601 strings.
export type Role = "user" | "assistant";

export interface SourceRef {
  url: string;
  title: string;
}

export interface Source extends SourceRef {
  text: string;
}

export interface ImageRef {
  id: string;
  media_type: string;
}

// What the browser uploads: base64 without the `data:` prefix.
export interface ImageUpload {
  media_type: string;
  data: string;
}

export interface Message {
  role: Role;
  content: string;
  created: string;
  images: ImageRef[];
  // Pages read for this turn; only user messages carry them.
  sources: Source[];
  // The search query actually sent to the web search; absent on older chats.
  query?: string | null;
}

export interface LoreEntry {
  id: string;
  name: string;
  keys: string[];
  content: string;
  enabled: boolean;
}

export interface Chat {
  id: string;
  title: string;
  created: string;
  updated: string;
  messages: Message[];
  bible: string;
  lore: LoreEntry[];
  // Condenses the first `summary_upto` messages; the model sees it instead of them.
  summary: string;
  summary_upto: number;
  last_usage: { prompt_tokens: number } | null;
}

export interface StoryBody {
  bible: string;
  lore: LoreEntry[];
}

export interface SummaryBody {
  summary: string;
  summary_upto: number;
}

export interface ContextParts {
  system: number;
  bible: number;
  lore: number;
  summary: number;
  history: number;
}

export interface ContextInfo {
  used: number;
  window: number | null;
  // "provider" = prompt tokens the API reported; "estimate" = counted from text length.
  source: "provider" | "estimate";
  parts: ContextParts;
}

// The chat as sent in the SSE `done` event.
export type DoneChat = Chat & { usage: { prompt_tokens: number } | null; context: ContextInfo };

export interface ChatSummary {
  id: string;
  title: string;
  updated: string;
  message_count: number;
}

export interface Profile {
  id: string;
  name: string;
  base_url: string;
  model: string;
  needs_key: boolean;
  vision: boolean;
  configured: boolean;
  last4: string | null;
  source: "keychain" | "env" | null;
  context_window: number | null;
}

export interface ProfileList {
  active: string | null;
  profiles: Profile[];
}

export interface NewProfileBody {
  name: string;
  base_url: string;
  model: string;
  needs_key: boolean;
  vision: boolean;
  key?: string;
  context_window?: number | null;
}

// For context_window, omitted leaves it unchanged and null clears it.
export type EditProfileBody = Partial<
  Pick<NewProfileBody, "name" | "base_url" | "model" | "vision" | "key" | "context_window">
>;

export interface WebStatus {
  configured: boolean;
  last4: string | null;
}

export interface ModelsQuery {
  profile_id?: string;
  base_url?: string;
  key?: string;
  needs_key?: boolean;
}

export interface ModelsResult {
  models: string[];
  context_windows?: Record<string, number>;
}
