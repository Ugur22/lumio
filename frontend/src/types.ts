// The shapes of the API are generated from models.py into api.gen.ts (`make types`); `make check` fails when it is stale.
// This file gives them their short names and holds what the schema cannot describe: SSE payloads and live-only state.
import type { components } from "./api.gen";

type Schema<K extends keyof components["schemas"]> = components["schemas"][K];

export type Role = Schema<"Message">["role"];

// Live-only: the server reports a failed illustration but does not store it.
export interface IllustrationFailure {
  prompt: string;
  status: number | null;
  detail: string;
}

export type Source = Schema<"Source">;
export type SourceRef = Pick<Source, "url" | "title">;
export type ImageRef = Schema<"ImageRef">;
// What the browser uploads: base64 without the `data:` prefix.
export type ImageUpload = Schema<"ImageData">;
export type Message = Schema<"Message">;
export type LoreEntry = Schema<"LoreEntry-Output">;
export type Chat = Schema<"Chat">;
export type ChatSummary = Schema<"ChatSummary">;

// null model clears the override (and the window); a null window means the model's size is unknown.
export type ChatModelBody = Schema<"ChatModelUpdate">;
// Omitted profile_id leaves the chat's provider alone; null clears it (follow the default).
export type BehaviorBody = Schema<"BehaviorUpdate">;
export type StoryBody = Schema<"StoryUpdate">;
export type SummaryBody = Schema<"SummaryUpdate">;

export type ContextParts = Schema<"ContextParts">;
export type ContextInfo = Schema<"ContextInfo">;

// The chat as sent in the SSE `done` event.
export type DoneChat = Chat & { usage: Schema<"Usage"> | null; context: ContextInfo };

export type Profile = Schema<"ProfileView">;
// Where the server keeps saved keys: the OS keychain locally, a file on a deployed host.
export type KeyStore = Profile["key_store"];
export type ProfileList = Schema<"ProfileList">;
export type NewProfileBody = Schema<"NewProfile">;
// For context_window and image_model, omitted leaves it unchanged and null clears it.
export type EditProfileBody = Schema<"EditProfile">;

export type WebStatus = Schema<"WebStatus">;
export type ModelsQuery = Schema<"ModelsQuery">;
export type ModelsResult = Schema<"ModelsResult">;

export type UserView = Schema<"UserView">;
export type LoginBody = Schema<"LoginBody">;
export type RegisterBody = Schema<"RegisterBody">;
export type PasswordChange = Schema<"PasswordChange">;
