// Mirrors models.py. Datetimes arrive as ISO-8601 strings.
export type Role = "user" | "assistant";

// Live-only: the server reports a failed illustration but does not store it.
export interface IllustrationFailure {
  prompt: string;
  status: number | null;
  detail: string;
}

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
  // The description an illustration was generated from; used as its caption.
  prompt?: string | null;
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
  // Per-chat behavior; null means the setting is not sent and the provider's default applies.
  system_prompt: string;
  temperature: number | null;
  top_p: number | null;
  frequency_penalty: number | null;
  max_tokens: number | null;
  // The provider this chat talks to; null follows the global default.
  profile_id: string | null;
  // Per-chat model override, set together with its context window; null model follows the profile.
  model: string | null;
  context_window: number | null;
}

// null model clears the override (and the window); a null window means the model's size is unknown.
export interface ChatModelBody {
  model: string | null;
  context_window: number | null;
}

export interface BehaviorBody {
  system_prompt: string;
  temperature: number | null;
  top_p: number | null;
  frequency_penalty: number | null;
  max_tokens: number | null;
  // Omitted leaves the chat's provider alone; null clears it (follow the default).
  profile_id?: string | null;
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
  key_store: KeyStore;
  context_window: number | null;
  // Set when the provider can generate images; enables the Illustrate toggle.
  image_model: string | null;
}

// Where the server keeps saved keys: the OS keychain locally, a file on a deployed host.
export type KeyStore = "keychain" | "file";

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
  image_model?: string | null;
}

// For context_window and image_model, omitted leaves it unchanged and null clears it.
export type EditProfileBody = Partial<
  Pick<NewProfileBody, "name" | "base_url" | "model" | "vision" | "key" | "context_window" | "image_model">
>;

export interface WebStatus {
  configured: boolean;
  last4: string | null;
  key_store: KeyStore;
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
