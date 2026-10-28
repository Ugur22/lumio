import { animated, useTrail } from "@react-spring/web";
import { useEffect, useRef } from "react";
import { match } from "ts-pattern";
import { imageUrl } from "../api";
import { useStream } from "../store/stream";
import type { Message, SourceRef } from "../types";
import { LumioMark } from "./icons";
import { PressButton } from "./PressButton";
import { Turn, type Reply } from "./Turn";

interface Props {
  messages: Message[];
  chatId: string | null;
  onPick: (text: string) => void;
}

const SUGGESTIONS = [
  { title: "Open a story", text: "Write the opening scene of a noir story set in a rainy harbour town." },
  { title: "Continue the scene", text: "Two rivals are stuck in a stalled elevator. Continue the scene, with dialogue." },
  { title: "Tighten my writing", text: "Review this paragraph and point out what to tighten:\n\n" },
  { title: "Explain simply", text: "Explain a hard idea to me as if I'm new to it, with one concrete example." },
];

export function MessageList({ messages, chatId, onPick }: Props) {
  const ref = useRef<HTMLElement>(null);
  const stored = useStream((s) => s.pending);
  const liveSources = useStream((s) => s.sources);
  const liveNotes = useStream((s) => s.notes);
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
  const turns: { question: string; images: string[]; reply: Reply; sources: SourceRef[]; notes: string[] }[] = [];
  for (let i = 0; i < messages.length; i += 2) {
    const q = messages[i];
    const a = messages[i + 1];
    if (q) {
      const reply: Reply = a ? { kind: "text", content: a.content } : { kind: "none" };
      const images = chatId ? q.images.map((r) => imageUrl(chatId, r.id)) : [];
      turns.push({ question: q.content, images, reply, sources: q.sources, notes: [] });
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
    });
  }

  return (
    <section
      ref={ref}
      aria-live={streaming ? "off" : "polite"}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }} className="flex-1 overflow-y-auto px-5 py-6"
    >
      <div className="mx-auto max-w-[720px]">
        {turns.length === 0 ? (
          <EmptyState onPick={onPick} />
        ) : (
          turns.map((t, i) => <Turn key={i} question={t.question} images={t.images} reply={t.reply} sources={t.sources} notes={t.notes} />)
        )}
      </div>
    </section>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  const trail = useTrail(SUGGESTIONS.length + 1, {
    from: { opacity: 0, y: 18 },
    to: { opacity: 1, y: 0 },
    config: { tension: 220, friction: 24 },
  });
  const [hero, ...cards] = trail;

  return (
    <div className="mt-[10vh]">
      <animated.div style={hero} className="mb-8 text-center">
        <LumioMark size={56} className="mx-auto mb-5 drop-shadow-lg" />
        <h2 className="font-display text-[2.1rem] font-semibold leading-tight">What shall we write?</h2>
        <p className="mt-2 text-muted">Stories, scenes and ideas. Dialogue, actions and key moments stay styled.</p>
      </animated.div>
      <div className="grid gap-3 sm:grid-cols-2">
        {cards.map((style, i) => {
          const s = SUGGESTIONS[i];
          if (!s) return null;
          return (
            <animated.div key={s.title} style={style}>
              <PressButton
                type="button"
                hover={1.02}
                press={0.98}
                onClick={() => onPick(s.text)}
                className="h-full w-full rounded-2xl border border-border bg-surface p-4 text-left shadow-soft transition-colors hover:border-accent/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                <span className="block font-display text-base font-semibold">{s.title}</span>
                <span className="mt-1 block text-sm text-muted">{s.text.trim()}</span>
              </PressButton>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}
