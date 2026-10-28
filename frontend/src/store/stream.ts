import { create } from "zustand";

// A discriminated union, so consumers can match it exhaustively. "Succeeded" is `pending: null`:
// the saved chat then supplies the reply.
export type Pending = { text: string; chatId: string | null } & (
  | { status: "thinking" }
  | { status: "streaming"; reply: string }
  | { status: "error"; error: string }
);

interface StreamState {
  pending: Pending | null;
  start: (chatId: string | null, text: string) => void;
  setReply: (reply: string) => void;
  fail: (error: string) => void;
  clear: () => void;
}

// Lives outside App so per-frame reply updates re-render only the components that select `pending`.
export const useStream = create<StreamState>((set) => ({
  pending: null,
  start: (chatId, text) => set({ pending: { text, chatId, status: "thinking" } }),
  // A failed turn keeps showing its error; a late frame must not turn it back into a reply.
  setReply: (reply) =>
    set((s) =>
      s.pending && s.pending.status !== "error"
        ? { pending: { text: s.pending.text, chatId: s.pending.chatId, status: "streaming", reply } }
        : s,
    ),
  fail: (error) =>
    set((s) =>
      s.pending ? { pending: { text: s.pending.text, chatId: s.pending.chatId, status: "error", error } } : s,
    ),
  clear: () => set({ pending: null }),
}));
