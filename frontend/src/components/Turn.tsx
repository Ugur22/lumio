import { animated, useSpring, useTrail } from "@react-spring/web";
import { useRef, useState, type ComponentPropsWithoutRef } from "react";
import { match } from "ts-pattern";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { APP_NAME } from "../lib/brand";
import { hostOf } from "../lib/providers";
import type { SourceRef } from "../types";
import { LumioMark } from "./icons";
import { ImageLightbox } from "./ImageLightbox";
import { Markup } from "./Markup";

export type Reply =
  | { kind: "text"; content: string; streaming?: boolean }
  | { kind: "thinking" }
  | { kind: "error"; message: string }
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
}

export function Turn({ question, images = [], reply, sources = [], notes = [], query = null }: TurnProps) {
  // A turn that mounts while still waiting for its reply is new; history mounts with its reply.
  const [live] = useState(reply.kind === "thinking");

  return (
    <div className="mb-8 [&:not(:first-child)]:border-t [&:not(:first-child)]:border-border [&:not(:first-child)]:pt-8">
      <AttachedImages urls={images} live={live} />
      {question && (
        <Appear
          live={live}
          className="ml-auto w-fit max-w-[85%] origin-right whitespace-pre-wrap break-words rounded-[12px_12px_3px_12px] bg-bubble px-4 py-2.5 shadow-soft [overflow-wrap:anywhere]"
        >
          {question}
        </Appear>
      )}
      <SourceChips sources={sources} notes={notes} query={query} />
      {match(reply)
        .with({ kind: "text" }, (r) => (
          <Appear live={live} className="mt-5">
            <Who />
            <Markup text={r.content} streaming={r.streaming} />
          </Appear>
        ))
        .with({ kind: "thinking" }, () => (
          <div className="mt-5">
            <Who />
            <ThinkingDots />
          </div>
        ))
        .with({ kind: "error" }, (r) => (
          <Appear
            live
            role="alert"
            className="mt-5 rounded-xl border border-warn-bar/40 bg-warn-bg px-4 py-3 text-warn-bar"
          >
            Failed: {r.message}
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
    <Appear live={live} className="mb-2 ml-auto flex max-w-[85%] flex-wrap justify-end gap-2">
      {urls.map((url, i) => (
        <AttachedImage key={url} url={url} label={`Attached image ${i + 1}`} />
      ))}
    </Appear>
  );
}

// Images are pruned after a while; the server then answers 410 and the chat keeps a placeholder.
function AttachedImage({ url, label }: { url: string; label: string }) {
  const [expired, setExpired] = useState(false);
  const [open, setOpen] = useState(false);
  const thumb = useRef<HTMLButtonElement>(null);

  if (expired) {
    return (
      <span className="grid h-28 w-28 place-items-center rounded-xl border border-dashed border-border px-2 text-center text-[12px] text-muted">
        Image no longer stored
      </span>
    );
  }
  return (
    <>
      <button
        ref={thumb}
        type="button"
        aria-label={`View ${label.toLowerCase()} full size`}
        title="View full size"
        onClick={() => setOpen(true)}
        // Hidden while the lightbox shows it, so the image looks lifted off the page rather than copied.
        className={`block cursor-zoom-in rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          open ? "invisible" : ""
        }`}
      >
        <img
          src={url}
          alt={label}
          onError={() => setExpired(true)}
          className="max-h-48 max-w-full rounded-xl border border-border object-cover shadow-soft sm:max-h-56"
        />
      </button>
      {open && (
        <ImageLightbox
          src={url}
          alt={label}
          getOrigin={() => {
            const el = thumb.current;
            if (!el) return null;
            const bounds = el.closest("[data-image-bounds]")?.getBoundingClientRect() ?? null;
            return { thumb: el.getBoundingClientRect(), bounds };
          }}
          onClose={() => {
            setOpen(false);
            // preventScroll: refocusing a partly hidden thumbnail must not scroll the chat.
            thumb.current?.focus({ preventScroll: true });
          }}
        />
      )}
    </>
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
    <div className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold leading-none text-muted">
      <LumioMark size={20} />
      {APP_NAME}
    </div>
  );
}

function ThinkingDots() {
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const dots = useTrail(3, {
    from: { y: 0, opacity: 0.35 },
    to: [
      { y: -5, opacity: 1 },
      { y: 0, opacity: 0.35 },
    ],
    loop: true,
    config: { tension: 300, friction: 14 },
  });

  // A looping spring would spin when springs are skipped, so reduced motion gets plain text.
  if (reduceMotion) return <div className="italic text-muted">Thinking…</div>;

  return (
    <div role="status" aria-label="Thinking" className="flex h-6 items-center gap-1.5">
      {dots.map((style, i) => (
        <animated.span key={i} style={style} className="size-2 rounded-full bg-accent" />
      ))}
    </div>
  );
}
