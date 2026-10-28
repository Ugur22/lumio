import { useState } from "react";
import { formatTokens, meterView, partRows, type ContextLevel } from "../lib/context";
import type { ContextInfo } from "../types";

interface Props {
  // Undefined while the first measurement is loading or if it failed; the meter then stays out of the way.
  context: ContextInfo | undefined;
  onSetWindow: () => void;
  onSummarize: () => void;
}

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

const BAR: Record<ContextLevel, string> = { ok: "bg-accent", warn: "bg-caution", high: "bg-warn-bar" };
const TEXT: Record<ContextLevel, string> = { ok: "text-muted", warn: "text-caution", high: "text-warn-bar" };

export function ContextMeter({ context, onSetWindow, onSummarize }: Props) {
  const [pinned, setPinned] = useState(false);
  if (!context) return null;

  const view = meterView(context);

  if (!view) {
    return (
      <p className="mx-auto w-full max-w-[720px] px-5 pt-2 text-center text-xs text-muted">
        {formatUsed(context)}
        <button type="button" onClick={onSetWindow} className={`rounded underline hover:text-text ${focus}`}>
          Set context size
        </button>
      </p>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-wrap items-center gap-x-3 gap-y-1 px-5 pt-2 text-xs">
      {/* Hover and keyboard focus reveal the tip like the Composer's; a click pins it for touch screens. */}
      <div className="group relative min-w-[11rem] flex-1" onKeyDown={(e) => e.key === "Escape" && setPinned(false)}>
        <button
          type="button"
          aria-expanded={pinned}
          aria-describedby="context-tip"
          onClick={() => setPinned((on) => !on)}
          className={`flex w-full flex-col gap-1 rounded text-left ${focus}`}
        >
          <span className="flex items-baseline justify-between gap-2">
            <span className={`font-medium ${TEXT[view.level]}`}>
              {view.label} <span className="font-normal">tokens</span>
            </span>
            <span className="text-muted">{view.sourceLabel}</span>
          </span>
          <span
            role="meter"
            aria-label="Context used"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={view.barPercent}
            aria-valuetext={`${view.percent}% of the context window, ${view.sourceLabel}`}
            className="block h-1 overflow-hidden rounded-full bg-bubble"
          >
            <span
              className={`block h-full rounded-full motion-safe:transition-[width] motion-safe:duration-300 ${BAR[view.level]}`}
              style={{ width: `${view.barPercent}%` }}
            />
          </span>
        </button>
        <div
          id="context-tip"
          role="tooltip"
          className={`pointer-events-none absolute bottom-full left-0 z-20 mb-2.5 w-[min(16rem,calc(100vw-2.5rem))] rounded-xl border border-border bg-surface px-3 py-2.5 leading-snug text-text shadow-lift transition-opacity duration-150 group-has-[:focus-visible]:opacity-100 group-hover:opacity-100 ${
            pinned ? "opacity-100" : "opacity-0"
          }`}
        >
          <strong className="block text-[13px] font-semibold">
            {view.percent}% of the context window
          </strong>
          <dl className="mt-1.5 grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5">
            {partRows(context.parts).map((r) => (
              <div key={r.key} className="contents">
                <dt className="text-muted">{r.label}</dt>
                <dd className="text-right tabular-nums">{r.tokens}</dd>
              </div>
            ))}
          </dl>
          <span className="mt-1.5 block text-muted">
            {context.source === "provider"
              ? "Total is what the provider counted on the last reply. The breakdown is estimated."
              : "Estimated from text length; the provider has not reported a count yet."}
          </span>
        </div>
      </div>
      {view.suggestSummary && (
        <button
          type="button"
          onClick={onSummarize}
          className={`rounded-lg border border-border bg-surface px-2.5 py-1 font-medium shadow-soft hover:text-accent ${focus}`}
        >
          Summarize older chapters
        </button>
      )}
    </div>
  );
}

function formatUsed(context: ContextInfo) {
  return context.used > 0 ? `${formatTokens(context.used)} tokens used · ` : "";
}
