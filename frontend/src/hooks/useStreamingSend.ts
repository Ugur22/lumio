import { useCallback, useRef } from "react";
import { useStream } from "../store/stream";
import type { Attachment } from "../lib/images";
import type { Chat } from "../types";
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
    (chatId: string | null, content: string, attachments: Attachment[], web: boolean, illustrate: boolean, onSaved: (chat: Chat) => void) => {
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
          signal: controller.signal, onDelta, onSources: useStream.getState().setSources },
        {
          onSuccess: (saved) => {
            endStream();
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

  return { send, stop, isPending };
}
