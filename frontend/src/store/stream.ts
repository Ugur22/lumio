import { create } from "zustand";
import type { IllustrationFailure, SourceRef } from "../types";

// A discriminated union, so consumers can match it exhaustively. "Succeeded" is `pending: null`:
// the saved chat then supplies the reply.
// `images` are object URLs for the thumbnails; the store owns them from `start` and revokes them on clear.
export type Pending = { text: string; chatId: string | null; images: string[] } & (
  | { status: "thinking" }
  | { status: "streaming"; reply: string }
  | { status: "error"; error: string }
);

interface StreamState {
  pending: Pending | null;
  // What the server read for the turn in flight; the saved message takes over once it is done.
  sources: SourceRef[];
  notes: string[];
  query: string | null;
  // Failed illustrations of the turn just sent. They outlive `clear` (the saved chat replaces the
  // pending turn) and go away on the next send or when the chat changes. `failuresChatId` is null
  // until the chat is known.
  failures: IllustrationFailure[];
  failuresChatId: string | null;
  addFailure: (failure: IllustrationFailure) => void;
  settleFailures: (chatId: string) => void;
  clearFailures: () => void;
  start: (chatId: string | null, text: string, images?: string[]) => void;
  setReply: (reply: string) => void;
  setSources: (sources: SourceRef[], notes: string[], query?: string | null) => void;
  fail: (error: string) => void;
  clear: () => void;
}

// Lives outside App so per-frame reply updates re-render only the components that select `pending`.
function revoke(pending: Pending | null) {
  pending?.images.forEach((url) => URL.revokeObjectURL(url));
}

export const useStream = create<StreamState>((set, get) => ({
  pending: null,
  sources: [],
  notes: [],
  query: null,
  failures: [],
  failuresChatId: null,
  addFailure: (failure) => set((s) => (s.pending ? { failures: [...s.failures, failure] } : s)),
  settleFailures: (chatId) => set((s) => (s.failures.length ? { failuresChatId: chatId } : s)),
  clearFailures: () => set({ failures: [], failuresChatId: null }),
  start: (chatId, text, images = []) => {
    revoke(get().pending);
    set({
      pending: { text, chatId, images, status: "thinking" },
      sources: [],
      notes: [],
      query: null,
      failures: [],
      failuresChatId: chatId,
    });
  },
  setSources: (sources, notes, query = null) => set((s) => (s.pending ? { sources, notes, query } : s)),
  // A failed turn keeps showing its error; a late frame must not turn it back into a reply.
  setReply: (reply) =>
    set((s) =>
      s.pending && s.pending.status !== "error"
        ? { pending: { ...s.pending, status: "streaming", reply } }
        : s,
    ),
  fail: (error) =>
    set((s) =>
      s.pending ? { pending: { text: s.pending.text, chatId: s.pending.chatId, images: s.pending.images, status: "error", error } } : s,
    ),
  clear: () => {
    revoke(get().pending);
    set({ pending: null, sources: [], notes: [], query: null });
  },
}));
