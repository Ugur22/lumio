import { useEffect, useRef, useState } from "react";
import { RUNTIME_LABEL, type Runtime } from "../lib/runner/languages";
import { buildFixPrompt, canFix } from "../lib/runner/fixPrompt";
import { atCap, buildStdin, CAP_NOTE, DIVERGED_NOTE, FEEDBACK_NOTE } from "../lib/runner/replay";
import { describeStatus, isBusy, type RunState } from "../lib/runner/state";
import { needsInput } from "../lib/runner/stdin";
import { useCodeActions } from "./CodeActionsContext";
import { CloseIcon, PlayIcon, SparklesIcon, SpinnerIcon, StopIcon } from "./icons";
import { Button } from "./ui";

// The code block is dark in both themes, so these are fixed colours like the ones in Markup.
export const blockButton =
  "inline-flex items-center gap-1 rounded-lg border border-[#444c56] px-2 py-0.5 font-sans text-xs text-[#c9d1d9] transition-colors motion-reduce:transition-none hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7ec4ae] disabled:cursor-default disabled:opacity-70 disabled:hover:bg-transparent";
const panel = "border-t border-[#3a342b] border-l-2";
const sectionLabel = "font-mono text-[10px] font-semibold uppercase tracking-wider";

export function RunButtons({
  runtime,
  busy,
  onRun,
  onStop,
}: {
  runtime: Runtime;
  busy: boolean;
  onRun: () => void;
  onStop: () => void;
}) {
  const label = RUNTIME_LABEL[runtime];
  if (!busy) {
    return (
      <Button variant="none"
        type="button"
        onClick={onRun}
        aria-label={`Run ${label} code`}
        title={`Run ${label} in an isolated sandbox`}
        className={blockButton}
      >
        <PlayIcon width={11} height={11} />
        Run
      </Button>
    );
  }
  return (
    <>
      <Button variant="none" type="button" disabled className={blockButton}>
        <SpinnerIcon width={12} height={12} className="motion-safe:animate-spin" />
        Running…
      </Button>
      <Button variant="none" type="button" onClick={onStop} aria-label="Stop running code" title="Stop" className={blockButton}>
        <StopIcon width={11} height={11} />
        Stop
      </Button>
    </>
  );
}

const KEYCAP = "pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 rounded border border-[#5a534a] bg-[#2a251e] px-1 font-sans text-[10px] leading-4 text-[#c9c1b2]";

// Sits inline after the program's own prompt text. While a replay runs it shows the submitted answer, disabled.
function PromptRow({ pending, onSubmit }: { pending: string | null; onSubmit: (line: string) => void }) {
  const [draft, setDraft] = useState("");
  // The field is focused on mount, so it starts out as focused.
  const [focused, setFocused] = useState(true);
  const ref = useRef<HTMLInputElement>(null);
  const locked = pending !== null;
  useEffect(() => {
    if (!locked) ref.current?.focus();
  }, [locked]);
  const hint = !locked && (focused || draft !== "");
  return (
    <span className="relative inline-block max-w-full align-baseline">
      <input
        ref={ref}
        type="text"
        value={locked ? pending : draft}
        disabled={locked}
        placeholder={locked ? undefined : "Type here, then Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSubmit(draft);
          }
        }}
        aria-label="Answer to the program's prompt"
        spellCheck={false}
        autoComplete="off"
        autoCapitalize="off"
        className={`inline-block w-[30ch] max-w-full rounded-t border-0 border-b-2 border-[#7ec4ae] bg-[#7ec4ae]/10 py-px pl-1.5 font-mono text-[#e7dfd0] caret-[#7ec4ae] [field-sizing:content] placeholder:italic placeholder:text-[#8c8377] hover:bg-[#7ec4ae]/15 focus:bg-[#7ec4ae]/20 focus:outline-none focus:ring-2 focus:ring-[#7ec4ae]/60 disabled:border-[#7ec4ae]/40 disabled:bg-transparent disabled:opacity-100 ${hint ? "pr-8" : "pr-1.5"} ${draft === "" && !locked ? "min-w-[30ch]" : "min-w-[8ch]"}`}
      />
      {hint && (
        <kbd aria-hidden className={KEYCAP}>
          ↵
        </kbd>
      )}
    </span>
  );
}

const mutedNote = "px-3 pb-2 font-sans text-[11px] text-[#9d9486]";

const STATUS_TONE: Partial<Record<RunState["status"], string>> = {
  ok: "text-[#7ec4ae]",
  error: "text-[#f0a08a]",
  timeout: "text-[#f0a08a]",
};

// Output is untrusted: it only ever goes into the tree as text children.
export function OutputPanel({
  state,
  runtime,
  onClear,
  onRerun,
  onAnswer,
}: {
  state: RunState;
  runtime: Runtime;
  onClear: () => void;
  onRerun: () => void;
  onAnswer: (line: string) => void;
}) {
  const body = useRef<HTMLDivElement>(null);
  const actions = useCodeActions();
  // Height of the last finished run, so the next run does not collapse the panel and jump the page.
  const [heldHeight, setHeldHeight] = useState(0);
  const shown = state.held ?? state;
  const idle = state.status === "idle";
  const busy = isBusy(state);
  useEffect(() => {
    const el = body.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.size, state.answers.length]);
  useEffect(() => {
    if (idle) setHeldHeight(0);
    else if (!busy && body.current) setHeldHeight(body.current.offsetHeight);
  }, [idle, busy, shown.size]);

  if (idle) return null;

  const waiting = needsInput(state);
  const replaying = state.held !== null && busy;
  const capped = atCap(state.answers.length);
  const prompt = replaying || (waiting && !capped);
  // The EOF traceback is noise: the program only ran out of lines to read.
  const visible = waiting || state.held ? shown.chunks.filter((c) => c.stream !== "stderr") : shown.chunks;
  const tone = waiting ? "" : (STATUS_TONE[state.status] ?? "");
  const status = waiting && capped ? "Answer limit reached" : describeStatus(state, runtime);
  return (
    <div aria-live="polite" className={`${panel} border-l-[#6f675b] bg-[#171410] text-[#e7dfd0]`}>
      <div className="flex items-center justify-between gap-2 px-3 pt-1.5 font-sans text-[11px] text-[#9d9486]">
        <span className="flex min-w-0 items-center gap-2">
          <span className={`${sectionLabel} text-[#c9c1b2]`}>Output</span>
          <span className={`flex min-w-0 items-center gap-1.5 ${tone}`}>
            {busy && <SpinnerIcon width={11} height={11} className="shrink-0 motion-safe:animate-spin" />}
            <span className="truncate">{status}</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {actions && !busy && canFix(state) && (
            <Button variant="none"
              type="button"
              onClick={() => actions.askAboutRun(buildFixPrompt(state, runtime, buildStdin(state.answers)))}
              disabled={actions.busy}
              aria-label="Ask the model to fix this code"
              title={actions.busy ? "Wait for the current reply to finish" : "Ask the model to fix this code"}
              className={blockButton}
            >
              <SparklesIcon width={12} height={12} />
              Fix with AI
            </Button>
          )}
          {!busy && (
            <Button variant="none" type="button" onClick={onRerun} aria-label={`Run ${RUNTIME_LABEL[runtime]} code again`} title="Run again" className={blockButton}>
              <PlayIcon width={11} height={11} />
              Run again
            </Button>
          )}
          <Button variant="none"
            type="button"
            onClick={onClear}
            aria-label="Clear output"
            title="Clear output"
            className="-mr-1 rounded p-1 text-[#9d9486] transition-colors motion-reduce:transition-none hover:bg-white/10 hover:text-[#e7dfd0] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7ec4ae]"
          >
          <CloseIcon width={12} height={12} />
          </Button>
        </span>
      </div>
      <div
        ref={body}
        tabIndex={0}
        role="region"
        aria-label="Output"
        style={heldHeight ? { minHeight: heldHeight } : undefined}
        className="max-h-60 overflow-auto whitespace-pre-wrap break-words px-3 pb-2.5 pt-1 font-mono text-[0.8rem] leading-relaxed focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#7ec4ae]"
      >
        {visible.map((c, i) => (
          <span key={i} className={c.stream === "stderr" ? "text-[#f0a08a]" : c.stream === "echo" ? "text-[#7ec4ae]" : undefined}>
            {c.text}
          </span>
        ))}
        {prompt && (
          <PromptRow
            key={`${state.answers.length}-${replaying}`}
            pending={replaying ? (state.answers[state.answers.length - 1] ?? "") : null}
            onSubmit={onAnswer}
          />
        )}
        {!busy && !prompt && shown.chunks.length === 0 && <span className="italic text-[#8c8377]">(no output)</span>}
      </div>
      {state.diverged && !busy && <p className={mutedNote}>{DIVERGED_NOTE}</p>}
      {state.feedback && !busy && <p className={mutedNote}>{FEEDBACK_NOTE[state.feedback]}</p>}
      {waiting && capped && <p className={mutedNote}>{CAP_NOTE}</p>}
    </div>
  );
}
