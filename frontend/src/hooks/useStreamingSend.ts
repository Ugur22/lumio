import { useCallback, useEffect, useRef, useState } from "react";
import { createSmoother } from "../lib/smoother";
import { useStream } from "../store/stream";
import type { Attachment } from "../lib/images";
import { trialFailure, type TrialFailure } from "../lib/trial";
import type { Chat, ChatModelBody } from "../types";
import { useSendMessage } from "./useChats";

interface Options {
  // The trial refused the send (used up, or full for today); the app opens Providers when it ended.
  onTrialRefused?: (failure: TrialFailure) => void;
  // There is no provider to send to (the first-run onboarding is showing); a send is dropped without an error.
  blocked?: boolean;
}

export function useStreamingSend({ onTrialRefused, blocked = false }: Options = {}) {
  const refusing = useRef(blocked);
  refusing.current = blocked;
  const refused = useRef(onTrialRefused);
  refused.current = onTrialRefused;
  const { mutate, isPending } = useSendMessage();
  const abort = useRef<AbortController | null>(null);
  const streamed = useRef("");
  const reasoned = useRef("");
  const frame = useRef(0);

  // Text is released on a fixed beat instead of as it arrives; each release is one store update, so markdown
  // is parsed at most once per beat.
  const [smoother] = useState(() =>
    createSmoother((chunk) => {
      streamed.current += chunk;
      useStream.getState().setReply(streamed.current);
    }),
  );

  // Reasoning is not smoothed, but it can arrive faster than frames, so it is applied once per frame.
  const flushReasoning = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    if (!reasoned.current) return;
    const text = reasoned.current;
    reasoned.current = "";
    useStream.getState().addReasoning(text);
  }, []);

  const onReasoning = useCallback(
    (text: string) => {
      reasoned.current += text;
      if (!frame.current) frame.current = requestAnimationFrame(flushReasoning);
    },
    [flushReasoning],
  );

  // Whatever is still buffered goes out at once, so what is shown matches what the server saves.
  const endStream = useCallback(() => {
    smoother.flush();
    flushReasoning();
    abort.current = null;
  }, [smoother, flushReasoning]);

  const onDelta = useCallback((text: string) => smoother.push(text), [smoother]);

  const send = useCallback(
    (chatId: string | null, content: string, attachments: Attachment[], web: boolean, illustrate: boolean, onSaved: (chat: Chat) => void, model?: ChatModelBody) => {
      // Not a failure: the composer and tiles are already locked, so this only catches paths that slip past them.
      if (refusing.current) return;
      const controller = new AbortController();
      abort.current = controller;
      streamed.current = "";
      reasoned.current = "";
      smoother.cancel();
      useStream.getState().start(
        chatId,
        content,
        attachments.map((a) => a.preview),
        illustrate,
      );
      mutate(
        {
          chatId,
          content,
          images: attachments.map((a) => a.upload),
          web,
          illustrate,
          model,
          signal: controller.signal,
          onDelta,
          onReasoning,
          onSources: useStream.getState().setSources,
          onIllustrationFailed: useStream.getState().addFailure,
        },
        {
          onSuccess: (saved) => {
            endStream();
            useStream.getState().settleFailures(saved.id);
            useStream.getState().settleReasoning(saved.id);
            useStream.getState().clear();
            onSaved(saved);
          },
          onError: (err) => {
            endStream();
            const trial = trialFailure(err);
            if (trial) {
              useStream.getState().fail(trial.message, true);
              refused.current?.(trial);
              return;
            }
            useStream.getState().fail(err.message);
          },
        },
      );
    },
    [mutate, onDelta, onReasoning, endStream, smoother],
  );

  // Stop shows the rest of the buffered text before aborting; the server saves exactly what it had streamed.
  const stop = useCallback(() => {
    smoother.flush();
    abort.current?.abort();
  }, [smoother]);

  // Leaving the app (sign-out, a lost session) ends a stream in flight instead of letting it write into a store
  // that now belongs to the next screen.
  useEffect(
    () => () => {
      abort.current?.abort();
      smoother.cancel();
      cancelAnimationFrame(frame.current);
    },
    [smoother],
  );

  return { send, stop, isPending };
}
