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
}

export interface Chat {
  id: string;
  title: string;
  created: string;
  updated: string;
  messages: Message[];
}

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
}

export type EditProfileBody = Partial<Pick<NewProfileBody, "name" | "base_url" | "model" | "vision" | "key">>;

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
