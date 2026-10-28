import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Chat, StoryBody, SummaryBody } from "../types";
import { chatKey, chatsKey, contextKey } from "./useChats";

// Story, summary and the context meter all derive from the saved chat, so every save refreshes the three.
function useStored(chatId: string) {
  const qc = useQueryClient();
  return (chat: Chat) => {
    qc.setQueryData(chatKey(chatId), chat);
    void qc.invalidateQueries({ queryKey: contextKey(chatId) });
    void qc.invalidateQueries({ queryKey: chatsKey });
  };
}

export function useSaveStory(chatId: string) {
  const stored = useStored(chatId);
  return useMutation({ mutationFn: (body: StoryBody) => api.saveStory(chatId, body), onSuccess: stored });
}

export function useSaveSummary(chatId: string) {
  const stored = useStored(chatId);
  return useMutation({ mutationFn: (body: SummaryBody) => api.saveSummary(chatId, body), onSuccess: stored });
}

// A proposal only: the server saves nothing, so there is no cache to update.
export function useSummarize(chatId: string) {
  return useMutation({ mutationFn: () => api.summarize(chatId) });
}
