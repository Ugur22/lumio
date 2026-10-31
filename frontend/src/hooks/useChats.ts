import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Chat, ChatModelBody, ContextInfo, IllustrationFailure, ImageUpload, SourceRef } from "../types";

export const chatsKey = ["chats"] as const;
export const chatKey = (id: string) => ["chat", id] as const;
export const contextKey = (id: string) => ["context", id] as const;

export function useChatList() {
  return useQuery({ queryKey: chatsKey, queryFn: api.listChats });
}

export function useChat(id: string | null) {
  return useQuery({
    queryKey: chatKey(id ?? ""),
    queryFn: () => api.getChat(id as string),
    enabled: id !== null,
  });
}

// staleTime 0 so opening a chat re-measures it; the global default would keep the first answer forever.
export function useChatContext(id: string | null) {
  return useQuery({
    queryKey: contextKey(id ?? ""),
    queryFn: () => api.getContext(id as string),
    enabled: id !== null,
    staleTime: 0,
  });
}

export function useCreateChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createChat,
    onSuccess: (chat) => {
      qc.setQueryData(chatKey(chat.id), chat);
      return qc.invalidateQueries({ queryKey: chatsKey });
    },
  });
}

// A model change moves the context window with it, so the meter is re-measured as well.
export function useSetChatModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ChatModelBody }) => api.setChatModel(id, body),
    onSuccess: (chat) => {
      qc.setQueryData(chatKey(chat.id), chat);
      void qc.invalidateQueries({ queryKey: chatKey(chat.id) });
      void qc.invalidateQueries({ queryKey: contextKey(chat.id) });
    },
  });
}

export function useRenameChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.renameChat(id, title),
    onSuccess: (chat) => {
      qc.setQueryData(chatKey(chat.id), chat);
      return qc.invalidateQueries({ queryKey: chatsKey });
    },
  });
}

export function useDeleteChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteChat(id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: chatKey(id) });
      return qc.invalidateQueries({ queryKey: chatsKey });
    },
  });
}

// `context` comes from the `done` event; the stop path has none and refetches instead.
export type SentChat = Chat & { context?: ContextInfo };

interface SendVars {
  chatId: string | null;
  content: string;
  images: ImageUpload[];
  web: boolean;
  illustrate: boolean;
  model?: ChatModelBody;
  signal: AbortSignal;
  onDelta: (text: string) => void;
  onSources: (sources: SourceRef[], notes: string[], query: string | null) => void;
  onIllustrationFailed: (failure: IllustrationFailure) => void;
}

// After Stop the server saves the partial reply on its own schedule, so poll briefly for it.
async function savedAfterStop(id: string, knownCount: number): Promise<Chat> {
  let chat = await api.getChat(id);
  for (let i = 0; i < 10 && chat.messages.length <= knownCount; i++) {
    await new Promise((r) => setTimeout(r, 100));
    chat = await api.getChat(id);
  }
  return chat;
}

// The chat file is created lazily so "New chat" never leaves empty files behind.
export function useSendMessage() {
  const qc = useQueryClient();
  return useMutation<SentChat, Error, SendVars>({
    mutationFn: async ({ chatId, content, images, web, illustrate, model, signal, onDelta, onSources, onIllustrationFailed }) => {
      const id = chatId ?? (await api.createChat()).id;
      // Chats are created before the first message, so the pick is stored with its own call.
      if (chatId === null && model) {
        try {
          await api.setChatModel(id, model);
        } catch (err) {
          await api.deleteChat(id).catch(() => undefined);
          throw err;
        }
      }
      const knownCount = chatId === null ? 0 : (qc.getQueryData<Chat>(chatKey(id))?.messages.length ?? 0);
      let received = false;
      try {
        return await api.sendMessage(id, content, {
          images,
          web,
          illustrate,
          signal,
          onSources,
          onIllustrationFailed,
          onDelta: (text) => {
            received = true;
            onDelta(text);
          },
        });
      } catch (err) {
        // Stopped before any text arrived: nothing was saved, same as a failure.
        if (signal.aborted && received) return await savedAfterStop(id, knownCount);
        // Drop the chat we just created so a failed first send leaves no empty file.
        if (chatId === null) await api.deleteChat(id).catch(() => undefined);
        throw err;
      }
    },
    onSuccess: ({ context, ...chat }) => {
      qc.setQueryData(chatKey(chat.id), chat);
      if (context) qc.setQueryData(contextKey(chat.id), context);
      else void qc.invalidateQueries({ queryKey: contextKey(chat.id) });
      return qc.invalidateQueries({ queryKey: chatsKey });
    },
    onError: () => qc.invalidateQueries({ queryKey: chatsKey }),
  });
}
