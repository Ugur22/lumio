import { animated, useSpring, useTrail } from "@react-spring/web";
import { useEffect, useRef, type Ref } from "react";
import { match } from "ts-pattern";
import { imageUrl } from "../api";
import { useStream } from "../store/stream";
import type { IllustrationFailure, Message, SourceRef } from "../types";
import { Button, PressButton } from "./ui";
import { Turn, type Reply } from "./Turn";

interface Props {
  messages: Message[];
  chatId: string | null;
  loading?: boolean;
}

// `send` tiles are complete requests; the others are templates that need the user's own text first.
const SUGGESTIONS = [
  { title: "Open a story", text: "Write the opening scene of a noir story set in a rainy harbour town.", send: true },
  { title: "Continue the scene", text: "Two rivals are stuck in a stalled elevator. Continue the scene, with dialogue.", send: true },
  { title: "Tighten my writing", text: "Review this paragraph and point out what to tighten:\n\n", send: false },
  { title: "Explain simply", text: "Explain a hard idea to me as if I'm new to it, with one concrete example.", send: false },
];

export function MessageList({ messages, chatId, loading = false }: Props) {
  const ref = useRef<HTMLElement>(null);
  const stored = useStream((s) => s.pending);
  const liveSources = useStream((s) => s.sources);
  const liveNotes = useStream((s) => s.notes);
  const liveQuery = useStream((s) => s.query);
  const failures = useStream((s) => s.failures);
  const failuresChatId = useStream((s) => s.failuresChatId);
  // A reply still streaming for another chat must not show up here.
  const pending = stored && stored.chatId === chatId ? stored : null;

  // Follow the stream only while the reader is at the bottom; scrolling up lets go.
  const stick = useRef(true);
  const streaming = pending?.status === "streaming";

  useEffect(() => {
    if (pending && pending.status !== "streaming") stick.current = true;
    const el = ref.current;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: streaming ? "auto" : "smooth" });
  }, [messages, pending, streaming]);

  // Messages alternate user/assistant, so pairing them gives one visual turn each.
  const turns: { question: string; images: string[]; reply: Reply; sources: SourceRef[]; notes: string[]; query: string | null; failures: IllustrationFailure[] }[] = [];
  for (let i = 0; i < messages.length; i += 2) {
    const q = messages[i];
    const a = messages[i + 1];
    if (q) {
      const illustrations = chatId && a ? a.images.map((r) => ({ id: r.id, url: imageUrl(chatId, r.id), prompt: r.prompt ?? null })) : [];
      const reply: Reply = a ? { kind: "text", content: a.content, illustrations } : { kind: "none" };
      const images = chatId ? q.images.map((r) => imageUrl(chatId, r.id)) : [];
      turns.push({ question: q.content, images, reply, sources: q.sources, notes: [], query: q.query ?? null, failures: [] });
    }
  }
  if (pending) {
    turns.push({
      question: pending.text,
      images: pending.images,
      reply: match(pending)
        .returnType<Reply>()
        .with({ status: "thinking" }, () => ({ kind: "thinking" }))
        .with({ status: "streaming" }, (p) => ({ kind: "text", content: p.reply, streaming: true }))
        .with({ status: "error" }, (p) => ({ kind: "error", message: p.error }))
        .exhaustive(),
      sources: liveSources,
      notes: liveNotes,
      query: liveQuery,
      failures: pending.chatId === failuresChatId ? failures : [],
    });
  } else if (chatId && failuresChatId === chatId) {
    // The turn just sent is now saved; the notes stay on its reply until the next send or chat switch.
    const last = turns[turns.length - 1];
    if (last && last.reply.kind === "text") last.failures = failures;
  }

  return (
    <section
      ref={ref}
      data-image-bounds
      aria-live={streaming ? "off" : "polite"}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
      // Blank chat: the heading hugs the composer below instead of floating at the top.
      className={`flex-1 overflow-y-auto overflow-x-hidden px-5 py-6 max-[720px]:px-4 [overflow-wrap:anywhere] ${turns.length === 0 ? "flex flex-col justify-end" : ""}`}
    >
      <div className="mx-auto w-full max-w-[720px]">
        {turns.length === 0 ? (
          loading ? null : <EmptyHeading />
        ) : (
          turns.map((t, i) => <Turn key={i} question={t.question} images={t.images} reply={t.reply} sources={t.sources} notes={t.notes} query={t.query} failures={t.failures} />)
        )}
      </div>
    </section>
  );
}

function EmptyHeading() {
  const style = useSpring({ from: { opacity: 0, y: 18 }, to: { opacity: 1, y: 0 }, config: { tension: 220, friction: 24 } });
  return (
    <animated.div style={style} className="mb-2">
      <h2 className="font-display text-[2.1rem] font-semibold leading-tight">What shall we write?</h2>
      <p className="mt-2 text-muted">Pick a starting point, or just start typing.</p>
    </animated.div>
  );
}

// Rendered under the composer on a blank chat, so the input sits where the eye already is.
export function Starters({ ref, leavingAt, onPick, onStory, disabled }: { ref?: Ref<HTMLDivElement>; leavingAt?: number; onPick: (text: string, send: boolean) => void; onStory: () => void; disabled: boolean }) {
  const trail = useTrail(SUGGESTIONS.length, {
    from: { opacity: 0, y: 18 },
    to: { opacity: 1, y: 0 },
    config: { tension: 220, friction: 24 },
  });

  return (
    <div
      ref={ref}
      // Leaving: fade in place without holding layout space, so the composer can dock underneath.
      style={leavingAt === undefined ? undefined : { position: "absolute", top: leavingAt, left: 0, right: 0 }}
      className={`mx-auto w-full max-w-[760px] px-5 pb-6 transition-opacity duration-200 ${leavingAt === undefined ? "" : "pointer-events-none opacity-0"}`}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {trail.map((style, i) => {
          const s = SUGGESTIONS[i];
          if (!s) return null;
          return (
            <animated.div key={s.title} style={style}>
              <PressButton
                type="button"
                press={0.98}
                disabled={disabled && s.send}
                onClick={() => onPick(s.text, s.send)}
                className="h-full w-full rounded-2xl border border-border bg-surface p-4 text-left shadow-soft transition-colors hover:border-accent/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
              >
                <span className="block font-display text-base font-semibold">{s.title}</span>
                <span className="mt-1 block text-sm text-muted">{s.text.trim()}</span>
              </PressButton>
            </animated.div>
          );
        })}
      </div>
      <p className="mt-6 text-sm text-muted">
        Writing something longer?{" "}
        <Button variant="bare"
          type="button"
          onClick={onStory}
          className="rounded text-accent underline underline-offset-2 hover:brightness-90"
        >
          Set up your story
        </Button>{" "}
        so the characters and world stay consistent.
      </p>
    </div>
  );
}
