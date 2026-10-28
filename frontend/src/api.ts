import { createSseParser } from "./lib/sse";
import type {
  Chat,
  ChatSummary,
  EditProfileBody,
  ImageUpload,
  ModelsQuery,
  NewProfileBody,
  ProfileList,
  SourceRef,
  WebStatus,
} from "./types";

interface ValidationIssue {
  msg?: string;
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = (detail as ValidationIssue[]).map((d) => d.msg).filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return detail == null ? fallback : JSON.stringify(detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch("/api" + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(errorMessage(body.detail, res.statusText || `HTTP ${res.status}`));
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

interface StreamOptions {
  images: ImageUpload[];
  web: boolean;
  signal: AbortSignal;
  onDelta: (text: string) => void;
  onSources: (sources: SourceRef[], notes: string[], query: string | null) => void;
}

// Resolves with the saved chat once the server sends `done`. Aborting rejects with an
// AbortError; the server then saves whatever text it had already streamed.
async function streamMessage(id: string, content: string, opts: StreamOptions): Promise<Chat> {
  const { images, web, signal, onDelta, onSources } = opts;
  const res = await fetch(`/api/chats/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, images, web }),
    signal,
  });
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(errorMessage(body.detail, res.statusText || `HTTP ${res.status}`));
  }

  let chat: Chat | null = null;
  let failure: string | null = null;
  const feed = createSseParser(({ event, data }) => {
    const payload = JSON.parse(data) as Record<string, unknown>;
    if (event === "delta") onDelta(payload.text as string);
    else if (event === "sources") onSources(
        (payload.sources as SourceRef[] | undefined) ?? [],
        (payload.notes as string[] | undefined) ?? [],
        typeof payload.query === "string" ? payload.query : null,
      );
    else if (event === "done") chat = payload as unknown as Chat;
    else if (event === "error") failure = errorMessage(payload.detail, "Stream failed");
  });

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    feed(value);
  }

  if (failure !== null) throw new Error(failure);
  if (chat === null) throw new Error("Connection closed before the reply finished");
  return chat;
}

export const imageUrl = (chatId: string, imageId: string) => `/api/chats/${chatId}/images/${imageId}`;

export const api = {
  listChats: () => request<ChatSummary[]>("/chats"),
  createChat: () => request<Chat>("/chats", { method: "POST" }),
  getChat: (id: string) => request<Chat>(`/chats/${id}`),
  renameChat: (id: string, title: string) =>
    request<Chat>(`/chats/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteChat: (id: string) => request<void>(`/chats/${id}`, { method: "DELETE" }),
  sendMessage: streamMessage,
  listProfiles: () => request<ProfileList>("/profiles"),
  createProfile: (body: NewProfileBody) =>
    request<ProfileList>("/profiles", { method: "POST", body: JSON.stringify(body) }),
  editProfile: (id: string, body: EditProfileBody) =>
    request<ProfileList>(`/profiles/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProfile: (id: string) => request<ProfileList>(`/profiles/${id}`, { method: "DELETE" }),
  activateProfile: (id: string) => request<ProfileList>(`/profiles/${id}/activate`, { method: "POST" }),
  getWebStatus: () => request<WebStatus>("/web"),
  setWebKey: (key: string) => request<WebStatus>("/web/key", { method: "PUT", body: JSON.stringify({ key }) }),
  deleteWebKey: () => request<WebStatus>("/web/key", { method: "DELETE" }),
  listModels: (body: ModelsQuery) =>
    request<{ models: string[] }>("/profiles/models", { method: "POST", body: JSON.stringify(body) }),
};
