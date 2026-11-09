import { animated, useSpring } from "@react-spring/web";
import { useState, type ComponentPropsWithoutRef } from "react";
import { match } from "ts-pattern";
import { APP_NAME } from "../lib/brand";
import { copyText } from "../lib/illustrations";
import { hostOf } from "../lib/providers";
import type { Illustration } from "../lib/illustrations";
import type { Thought } from "../lib/thinking";
import type { IllustrationFailure, SourceRef } from "../types";
import { AlertIcon, CheckIcon, CopyIcon, InfoIcon, LumioMark } from "./icons";
import { AttachedImage } from "./AttachedImage";
import { IllustrationNotes } from "./IllustrationNotes";
import { ReplyBody } from "./ReplyBody";
import { ThinkingStatus, ThoughtToggle } from "./ThinkingStatus";
import { Button } from "./ui";

export type Reply =
  // `thought` is the reasoning streamed live for this turn; it is never saved, so a reloaded chat has none.
  | { kind: "text"; content: string; streaming?: boolean; illustrate?: boolean; illustrations?: Illustration[]; thought?: Thought | null }
  | { kind: "thinking"; startedAt: number; reasoning: string }
  | { kind: "error"; message: string; notice?: boolean }
  | { kind: "none" };

type AppearProps = ComponentPropsWithoutRef<"div"> & { live: boolean };

// Only new content animates in; history that was already there stays still.
function Appear({ live, ...rest }: AppearProps) {
  const style = useSpring({
    from: live ? { opacity: 0, y: 14, scale: 0.985 } : { opacity: 1, y: 0, scale: 1 },
    to: { opacity: 1, y: 0, scale: 1 },
    config: { tension: 240, friction: 24 },
  });
  return <animated.div {...rest} style={style} />;
}

interface TurnProps {
  question: string;
  // URLs of the images attached to the question (stored ones, or local previews while sending).
  images?: string[];
  reply: Reply;
  sources?: SourceRef[];
  notes?: string[];
  // The rewritten search query the app sent, shown next to the sources.
  query?: string | null;
  // Illustrations that failed during the send that produced this reply (live only).
  failures?: IllustrationFailure[];
}

export function Turn({ question, images = [], reply, sources = [], notes = [], query = null, failures = [] }: TurnProps) {
  // A turn that mounts while still waiting for its reply is new; history mounts with its reply.
  const [live] = useState(reply.kind === "thinking");

  return (
    <div className="mb-8 max-[720px]:mb-5 [&:not(:first-child)]:border-t [&:not(:first-child)]:border-border [&:not(:first-child)]:pt-8 max-[720px]:[&:not(:first-child)]:border-t-0 max-[720px]:[&:not(:first-child)]:pt-0">
      <AttachedImages urls={images} live={live} />
      {question && (
        <Appear
          live={live}
          className="ml-auto w-fit max-w-[85%] origin-right whitespace-pre-wrap break-words rounded-[12px_12px_3px_12px] bg-bubble px-4 py-2.5 shadow-soft [overflow-wrap:anywhere] max-[720px]:max-w-[82%] max-[720px]:rounded-[18px_18px_4px_18px] max-[720px]:px-3.5 max-[720px]:py-[9px] max-[720px]:text-[15px] max-[720px]:shadow-none"
        >
          {question}
        </Appear>
      )}
      {/* While thinking, the status line shows the query and the domains itself. */}
      {reply.kind !== "thinking" && <SourceChips sources={sources} notes={notes} query={query} />}
      {match(reply)
        .with({ kind: "text" }, (r) => (
          <Appear live={live} className="mt-5">
            <Who />
            {r.thought && <ThoughtToggle thought={r.thought} />}
            <ReplyBody content={r.content} illustrations={r.illustrations} streaming={r.streaming} illustrate={r.illustrate} />
            {!r.streaming && <IllustrationNotes failures={failures} />}
            {!r.streaming && <CopyButton text={copyText(r.content)} />}
          </Appear>
        ))
        .with({ kind: "thinking" }, (r) => (
          <div className="mt-5">
            <Who />
            <ThinkingStatus startedAt={r.startedAt} reasoning={r.reasoning} query={query} sources={sources} />
          </div>
        ))
        .with({ kind: "error" }, (r) => (
          <Appear
            live
            role={r.notice ? "status" : "alert"}
            className={
              r.notice
                ? "mt-5 flex items-start gap-3 rounded-xl border border-border bg-note-bg px-4 py-3 text-text"
                : "mt-5 flex items-start gap-3 rounded-xl border border-warn-bar/40 bg-warn-bg px-4 py-3 text-warn-bar"
            }
          >
            {r.notice ? <InfoIcon className="mt-0.5 shrink-0" /> : <AlertIcon className="mt-0.5 shrink-0" />}
            <span className="min-w-0 [overflow-wrap:anywhere]">{r.notice ? r.message : `Failed: ${r.message}`}</span>
          </Appear>
        ))
        .with({ kind: "none" }, () => null)
        .exhaustive()}
    </div>
  );
}

function AttachedImages({ urls, live }: { urls: string[]; live: boolean }) {
  if (urls.length === 0) return null;
  return (
    <Appear live={live} className="mb-2 ml-auto flex max-w-[85%] max-[720px]:max-w-[82%] flex-wrap justify-end gap-2">
      {urls.map((url, i) => (
        <AttachedImage key={url} url={url} label={`Attached image ${i + 1}`} />
      ))}
    </Appear>
  );
}

// Page URLs come from the web, so only http(s) ones become links.
const isWebUrl = (url: string) => /^https?:\/\//i.test(url);

function SourceChips({ sources, notes, query }: { sources: SourceRef[]; notes: string[]; query: string | null }) {
  const searched = query?.trim() ?? "";
  if (sources.length === 0 && notes.length === 0 && !searched) return null;
  const chip = "max-w-full truncate rounded-lg border border-border bg-surface px-2 py-1";
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 text-[12px]">
      {searched && (
        <span className="max-w-full truncate text-muted" title={searched}>
          Searched: {searched}
        </span>
      )}
      {sources.length > 0 && (
        <span className="text-muted">
          Read {sources.length} {sources.length === 1 ? "source" : "sources"}
        </span>
      )}
      {sources.map((s) =>
        isWebUrl(s.url) ? (
          <a
            key={s.url}
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            title={s.title || s.url}
            className={`${chip} text-accent hover:border-accent/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent`}
          >
            {hostOf(s.url)}
          </a>
        ) : null,
      )}
      {notes.map((n) => (
        <span key={n} role="status" className="rounded-lg bg-warn-bg px-2 py-1 text-warn-bar">
          {n}
        </span>
      ))}
    </div>
  );
}

function Who() {
  return (
    // Phone replies run straight into the serif, like the mockup; the name row would only push them down.
    <div className="mb-2.5 flex items-center max-[720px]:hidden gap-2 text-[13px] font-semibold leading-none text-muted">
      <LumioMark size={20} />
      {APP_NAME}
    </div>
  );
}

// Copies the raw reply, not the rendered markup, so Markdown survives a paste.
function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 1500);
  }

  const label = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy message";
  return (
    <Button variant="bare"
      type="button"
      onClick={copy}
      aria-label={label}
      title={label}
      className="-ml-1.5 mt-2 grid size-7 place-items-center rounded-lg text-muted hover:bg-surface hover:text-text"
    >
      {state === "copied" ? <CheckIcon width={16} height={16} /> : <CopyIcon width={16} height={16} />}
    </Button>
  );
}
