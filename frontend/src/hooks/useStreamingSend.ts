import { useCallback, useEffect, useRef } from "react";
import { useStream } from "../store/stream";
import type { Attachment } from "../lib/images";
import type { Chat, ChatModelBody } from "../types";
import { useSendMessage } from "./useChats";

export function useStreamingSend() {
  const { mutate, isPending } = useSendMessage();
  const abort = useRef<AbortController | null>(null);
  const streamed = useRef("");
  const frame = useRef(0);

  const endStream = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    abort.current = null;
  }, []);

  // Deltas arrive faster than frames; one store update per frame keeps markdown parsing cheap.
  const onDelta = useCallback((text: string) => {
    streamed.current += text;
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      useStream.getState().setReply(streamed.current);
    });
  }, []);

  const send = useCallback(
    (chatId: string | null, content: string, attachments: Attachment[], web: boolean, illustrate: boolean, onSaved: (chat: Chat) => void, model?: ChatModelBody, transcriptId?: string | null) => {
      const controller = new AbortController();
      abort.current = controller;
      streamed.current = "";
      useStream.getState().start(
        chatId,
        content,
        attachments.map((a) => a.preview),
      );
      mutate(
        {
          chatId,
          content,
          images: attachments.map((a) => a.upload),
          web,
          illustrate,
          transcriptId,
          model,
          signal: controller.signal,
          onDelta,
          onSources: useStream.getState().setSources,
          onIllustrationFailed: useStream.getState().addFailure,
        },
        {
          onSuccess: (saved) => {
            endStream();
            useStream.getState().settleFailures(saved.id);
            useStream.getState().clear();
            onSaved(saved);
          },
          onError: (err) => {
            endStream();
            useStream.getState().fail(err.message);
          },
        },
      );
    },
    [mutate, onDelta, endStream],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  // Leaving the app (sign-out, a lost session) ends a stream in flight instead of letting it write into a store
  // that now belongs to the next screen.
  useEffect(
    () => () => {
      abort.current?.abort();
      cancelAnimationFrame(frame.current);
    },
    [],
  );

  return { send, stop, isPending };
}
