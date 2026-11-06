import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useElapsed } from "../hooks/useElapsed";
import { counterText, labelOf, phaseOf, sourceDomains, type Thought } from "../lib/thinking";
import type { SourceRef } from "../types";
import { ChevronDownIcon } from "./icons";

interface StatusProps {
  startedAt: number;
  reasoning: string;
  query: string | null;
  sources: readonly SourceRef[];
}

const chip = "max-w-full truncate rounded-full border border-border bg-surface px-2.5 py-[3px] font-mono text-xs";

// Replaces the bouncing dots while no reply text has been shown. Only the label is announced; the ticking
// counter is aria-hidden, and the chips and reasoning sit outside the live region so they are not re-read.
export function ThinkingStatus(props: StatusProps) {
  return <ThinkingView {...props} elapsedMs={useElapsed(props.startedAt)} />;
}

// The elapsed time comes in as a prop so the view can be rendered at any second.
export function ThinkingView({ elapsedMs, reasoning, query, sources }: Omit<StatusProps, "startedAt"> & { elapsedMs: number }) {
  const phase = phaseOf({ elapsedMs, reasoning, query, sources, hasText: false });
  if (phase === "writing") return null;
  const domains = sourceDomains(sources);
  const searched = query?.trim() ?? "";
  const counter = counterText(elapsedMs);

  return (
    // The surrounding message list is a polite live region; off here keeps the chips and the streaming reasoning quiet.
    <div aria-live="off">
      <div role="status" className="flex min-h-6 items-center gap-[9px] text-sm">
        <span
          aria-hidden="true"
          className="relative size-2 flex-none rounded-full bg-accent after:absolute after:-inset-1 after:rounded-full after:border-[1.5px] after:border-accent after:opacity-0 after:content-[''] motion-safe:after:animate-ring"
        />
        <span className="text-muted motion-safe:animate-sheen motion-safe:bg-[linear-gradient(90deg,var(--muted)_0%,var(--muted)_38%,var(--text)_50%,var(--muted)_62%,var(--muted)_100%)] motion-safe:bg-[length:250%_100%] motion-safe:bg-clip-text motion-safe:text-transparent">
          {labelOf(phase)}
        </span>
        <span aria-hidden="true" className="font-mono text-xs font-medium tabular-nums text-muted">
          {counter}
        </span>
      </div>
      {phase === "searching" && searched && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <span className={`${chip} text-text`} title={searched}>
            {searched}
          </span>
        </div>
      )}
      {phase === "reading" && domains.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {domains.map((d) => (
            <span key={d} className={`${chip} text-muted`}>
              {d}
            </span>
          ))}
        </div>
      )}
      {phase === "thinking" && <LiveThought text={reasoning} />}
    </div>
  );
}

// Reasoning is untrusted model output: it goes in as a text node, never as HTML or Markdown.
const thoughtText =
  "whitespace-pre-wrap border-l-2 border-border pl-3.5 font-serif text-sm italic leading-[1.6] text-muted [overflow-wrap:anywhere]";

function LiveThought({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);
  return (
    <div
      ref={ref}
      data-testid="live-thought"
      className={`${thoughtText} mt-2 max-h-[7.2em] overflow-hidden [-webkit-mask-image:linear-gradient(to_bottom,transparent_0,#000_45%)] [mask-image:linear-gradient(to_bottom,transparent_0,#000_45%)]`}
    >
      {text}
    </div>
  );
}

// "Thought for Ns", collapsed until asked. Only shown when the provider streamed reasoning for this turn.
export function ThoughtToggle({ thought }: { thought: Thought }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  // The panel keeps its scroll position closed; reopening starts at the top.
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open && panel.current) panel.current.scrollTop = 0;
  }, [open]);

  return (
    <div className="mb-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded py-0.5 text-sm text-muted hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <ChevronDownIcon
          size={14}
          className={`motion-safe:transition-transform motion-safe:duration-150 ${open ? "" : "-rotate-90"}`}
        />
        Thought for {thought.seconds}s
      </button>
      <div ref={panel} id={id} hidden={!open} className={`${thoughtText} mt-2 max-h-[15em] overflow-y-auto`}>
        {thought.text}
      </div>
    </div>
  );
}
