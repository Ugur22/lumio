import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { BehaviorBody, Chat, StoryBody, SummaryBody } from "../types";
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

export function useSaveBehavior(chatId: string) {
  const stored = useStored(chatId);
  return useMutation({ mutationFn: (body: BehaviorBody) => api.saveBehavior(chatId, body), onSuccess: stored });
}

// The behavior route resets any omitted field, so the chat's current values travel with the new provider.
export function useSwitchChatProfile(chat: Chat | undefined) {
  const save = useSaveBehavior(chat?.id ?? "");
  return {
    switchTo: (profileId: string) => {
      if (!chat) return;
      save.mutate({
        system_prompt: chat.system_prompt,
        temperature: chat.temperature,
        top_p: chat.top_p,
        frequency_penalty: chat.frequency_penalty,
        max_tokens: chat.max_tokens,
        profile_id: profileId,
      });
    },
    isPending: save.isPending,
    error: save.error,
  };
}

export function useSaveSummary(chatId: string) {
  const stored = useStored(chatId);
  return useMutation({ mutationFn: (body: SummaryBody) => api.saveSummary(chatId, body), onSuccess: stored });
}

// A proposal only: the server saves nothing, so there is no cache to update.
export function useSummarize(chatId: string) {
  return useMutation({ mutationFn: () => api.summarize(chatId) });
}
