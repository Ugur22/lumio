import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError } from "../api";
import { useChat } from "../hooks/useChats";
import { useSaveStory, useSaveSummary, useSummarize } from "../hooks/useStory";
import {
  blankDraft,
  isStoryDirty,
  loreProblems,
  MAX_BIBLE,
  MAX_CONTENT,
  MAX_LORE,
  MAX_NAME,
  MAX_SUMMARY,
  storyErrorText,
  toBody,
  toDraft,
  type LoreDraft,
  type StoryAction,
} from "../lib/story";
import type { Chat, StoryBody } from "../types";
import { TrashIcon } from "./icons";
import { PressButton } from "./PressButton";

export type StoryTab = "bible" | "lore" | "summary";

interface Props {
  open: boolean;
  chatId: string | null;
  // Which tab to land on each time the dialog opens.
  tab: StoryTab;
  onClose: () => void;
}

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const field = `rounded-xl border border-border bg-bg px-3 py-2 ${focus}`;
const secondary = `rounded-xl border border-border bg-surface px-3.5 py-2 text-muted shadow-soft hover:text-text disabled:opacity-50 ${focus}`;
const primary = `rounded-xl bg-accent px-3.5 py-2 font-medium text-white shadow-soft disabled:opacity-50 ${focus} focus-visible:outline-offset-2`;

const TABS: { id: StoryTab; label: string }[] = [
  { id: "bible", label: "Bible" },
  { id: "lore", label: "Lore" },
  { id: "summary", label: "Summary" },
];

const failure = (action: StoryAction, err: unknown) =>
  storyErrorText(action, err instanceof ApiError ? err.status : undefined, (err as Error).message);

export function StoryDialog({ open, chatId, tab, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  // A ref as well as state: the native close/cancel events must see the latest value synchronously.
  const dirty = useRef(false);
  const [warn, setWarn] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const onDirty = useCallback((d: boolean) => {
    dirty.current = d;
    if (!d) setWarn(false);
  }, []);

  function finish() {
    dirty.current = false;
    setWarn(false);
    onClose();
  }

  function requestClose() {
    if (dirty.current) setWarn(true);
    else finish();
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="story-title"
      // Escape: keep the dialog and explain, instead of silently dropping the edits.
      onCancel={(e) => {
        if (!dirty.current) return;
        e.preventDefault();
        setWarn(true);
      }}
      // Some browsers close on a second Escape regardless; reopen so the edits survive.
      onClose={() => {
        if (dirty.current) {
          ref.current?.showModal();
          setWarn(true);
        } else finish();
      }}
      onClick={(e) => e.target === ref.current && requestClose()}
      className="m-auto w-[min(94vw,40rem)] rounded-2xl border border-border bg-surface p-0 text-text shadow-lift backdrop:bg-black/40"
    >
      {open && chatId && (
        <StoryBody
          key={chatId}
          chatId={chatId}
          initialTab={tab}
          warn={warn}
          onDirty={onDirty}
          onClose={requestClose}
          onDiscard={finish}
          onKeepEditing={() => setWarn(false)}
        />
      )}
    </dialog>
  );
}

interface BodyProps {
  chatId: string;
  initialTab: StoryTab;
  warn: boolean;
  onDirty: (dirty: boolean) => void;
  onClose: () => void;
  onDiscard: () => void;
  onKeepEditing: () => void;
}

function StoryBody({ chatId, initialTab, ...rest }: BodyProps) {
  const { data, error } = useChat(chatId);
  if (!data) {
    return (
      <div className="flex flex-col gap-3 p-5">
        <h2 id="story-title" className="font-display text-lg font-semibold">Story</h2>
        {error ? <p role="alert" className="text-warn-bar">{error.message}</p> : <p className="text-muted">Loading…</p>}
        <button type="button" onClick={rest.onClose} className={`self-end rounded px-2 py-1 text-muted hover:text-text ${focus}`}>
          Close
        </button>
      </div>
    );
  }
  return <StoryEditor chat={data} initialTab={initialTab} {...rest} />;
}

interface SummaryDraft {
  text: string;
  upto: number;
  // Came from Generate and has never been saved.
  proposed: boolean;
}

function StoryEditor({
  chat,
  initialTab,
  warn,
  onDirty,
  onClose,
  onDiscard,
  onKeepEditing,
}: Omit<BodyProps, "chatId"> & { chat: Chat }) {
  const [tab, setTab] = useState<StoryTab>(initialTab);
  const [bible, setBible] = useState(chat.bible);
  const [lore, setLore] = useState<LoreDraft[]>(() => chat.lore.map(toDraft));
  const [summary, setSummary] = useState<SummaryDraft>({ text: chat.summary, upto: chat.summary_upto, proposed: false });

  const storyDirty = isStoryDirty(chat, bible, lore);
  const summaryDirty = summary.proposed || summary.text !== chat.summary;
  const dirty = storyDirty || summaryDirty;

  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);

  function onTabKey(e: KeyboardEvent) {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = TABS[(TABS.findIndex((t) => t.id === tab) + step + TABS.length) % TABS.length]?.id ?? tab;
    setTab(next);
    document.getElementById(`story-tab-${next}`)?.focus();
  }

  const unsaved: Record<StoryTab, boolean> = {
    bible: bible !== chat.bible,
    lore: isStoryDirty(chat, chat.bible, lore),
    summary: summaryDirty,
  };

  return (
    <div className="flex max-h-[min(90dvh,48rem)] flex-col">
      <div className="flex flex-col gap-3 px-5 pt-5">
        <h2 id="story-title" className="font-display text-lg font-semibold">
          Story
        </h2>
        <div role="tablist" aria-label="Story sections" onKeyDown={onTabKey} className="flex gap-1 border-b border-border">
          {TABS.map((t) => (
            <button
              key={t.id}
              id={`story-tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              aria-controls={`story-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => setTab(t.id)}
              className={`-mb-px rounded-t-lg border-b-2 px-3 py-2 text-[13px] font-medium ${focus} ${
                tab === t.id ? "border-accent text-text" : "border-transparent text-muted hover:text-text"
              }`}
            >
              {t.label}
              {unsaved[t.id] && (
                <>
                  <span aria-hidden="true" className="ml-1.5 inline-block size-1.5 rounded-full bg-caution align-middle" />
                  <span className="sr-only"> (unsaved changes)</span>
                </>
              )}
            </button>
          ))}
        </div>
      </div>

      <div
        id={`story-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`story-tab-${tab}`}
        className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
      >
        {tab === "bible" && <BibleTab value={bible} onChange={setBible} />}
        {tab === "lore" && <LoreTab drafts={lore} onChange={setLore} />}
        {tab === "summary" && <SummaryTab chat={chat} draft={summary} onChange={setSummary} />}
      </div>

      <div className="flex flex-col gap-2 border-t border-border px-5 py-3">
        {warn && dirty && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
            <span className="min-w-0 flex-1">You have unsaved changes. Save them first, or discard them to close.</span>
            <button type="button" onClick={onKeepEditing} className={`rounded px-2 py-1 font-medium ${focus}`}>
              Keep editing
            </button>
            <button type="button" onClick={onDiscard} className={`rounded px-2 py-1 font-medium underline ${focus}`}>
              Discard and close
            </button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {tab !== "summary" && (
            <StoryActions
              chatId={chat.id}
              dirty={storyDirty}
              problems={loreProblems(lore).size > 0}
              body={toBody(bible, lore)}
              onRevert={() => {
                setBible(chat.bible);
                setLore(chat.lore.map(toDraft));
              }}
            />
          )}
          <button type="button" onClick={onClose} className={`ml-auto rounded px-2 py-1 text-muted hover:text-text ${focus}`}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Counter({ n, max }: { n: number; max: number }) {
  return (
    <span className={`text-[12px] tabular-nums ${n >= max ? "text-warn-bar" : "text-muted"}`}>
      {n.toLocaleString()} / {max.toLocaleString()}
    </span>
  );
}

function StoryActions({
  chatId,
  dirty,
  problems,
  body,
  onRevert,
}: {
  chatId: string;
  dirty: boolean;
  problems: boolean;
  body: StoryBody;
  onRevert: () => void;
}) {
  const save = useSaveStory(chatId);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setError(null);
    try {
      await save.mutateAsync(body);
    } catch (err) {
      setError(failure("save-story", err));
    }
  }

  return (
    <>
      <PressButton type="button" onClick={run} disabled={!dirty || problems || save.isPending} hover={1.02} press={0.97} className={primary}>
        {save.isPending ? "Saving…" : "Save story"}
      </PressButton>
      <button type="button" onClick={onRevert} disabled={!dirty || save.isPending} className={`rounded px-2 py-1 text-muted hover:text-text disabled:opacity-50 ${focus}`}>
        Revert
      </button>
      <span role="status" className="text-[12px] text-muted">
        {error ? "" : dirty ? (problems ? "Fix the highlighted entries to save." : "Unsaved changes") : save.isSuccess ? "Saved" : ""}
      </span>
      {error && <p role="alert" className="basis-full text-warn-bar">{error}</p>}
    </>
  );
}

function BibleTab({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="story-bible" className="text-[13px] font-medium">
        Story bible
      </label>
      <p className="text-[12px] text-muted">
        Canon the model should always keep in mind: setting, characters, tone, rules. It is sent with every message.
      </p>
      <textarea
        id="story-bible"
        value={value}
        maxLength={MAX_BIBLE}
        rows={12}
        onChange={(e) => onChange(e.target.value)}
        className={`${field} min-h-48 resize-y`}
      />
      <div className="self-end">
        <Counter n={value.length} max={MAX_BIBLE} />
      </div>
    </div>
  );
}

function LoreTab({ drafts, onChange }: { drafts: LoreDraft[]; onChange: (d: LoreDraft[]) => void }) {
  const problems = loreProblems(drafts);
  const update = (id: string, patch: Partial<LoreDraft>) =>
    onChange(drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12px] text-muted">
        An enabled entry joins the model&apos;s context when one of its trigger keys appears as a whole word, ignoring
        case, in the last few messages or the message you are sending. Entries without keys are never used.
      </p>
      {drafts.length === 0 && <p className="text-muted">No lore yet. Add characters, places or items.</p>}
      <ul className="flex flex-col gap-3">
        {drafts.map((d, i) => {
          const problem = problems.get(d.id);
          return (
            <li
              key={d.id}
              className={`flex flex-col gap-2 rounded-xl border bg-bg p-3 ${problem ? "border-warn-bar" : "border-border"} ${d.enabled ? "" : "opacity-70"}`}
            >
              <div className="flex items-center gap-2">
                <input
                  aria-label={`Name of entry ${i + 1}`}
                  value={d.name}
                  maxLength={MAX_NAME}
                  placeholder="Name"
                  onChange={(e) => update(d.id, { name: e.target.value })}
                  className={`${field} min-w-0 flex-1 bg-surface`}
                />
                <label className="flex flex-none items-center gap-1.5 text-[13px]">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    onChange={(e) => update(d.id, { enabled: e.target.checked })}
                    className="size-4 accent-accent"
                  />
                  Enabled
                </label>
                <button
                  type="button"
                  aria-label={`Delete ${d.name.trim() || `entry ${i + 1}`}`}
                  onClick={() => onChange(drafts.filter((x) => x.id !== d.id))}
                  className={`flex-none rounded p-1.5 text-muted hover:text-warn-bar ${focus}`}
                >
                  <TrashIcon width={16} height={16} />
                </button>
              </div>
              <input
                aria-label={`Trigger keys for entry ${i + 1}`}
                value={d.keysText}
                placeholder="Trigger keys, comma separated"
                spellCheck={false}
                onChange={(e) => update(d.id, { keysText: e.target.value })}
                className={`${field} bg-surface`}
              />
              <textarea
                aria-label={`Content of entry ${i + 1}`}
                value={d.content}
                rows={3}
                placeholder="What the model should know when this comes up"
                onChange={(e) => update(d.id, { content: e.target.value })}
                className={`${field} resize-y bg-surface`}
              />
              <div className="flex items-center justify-between gap-2">
                <span role={problem ? "alert" : undefined} className="text-[12px] text-warn-bar">
                  {problem}
                </span>
                <Counter n={d.content.length} max={MAX_CONTENT} />
              </div>
            </li>
          );
        })}
      </ul>
      <PressButton
        type="button"
        disabled={drafts.length >= MAX_LORE}
        onClick={() => onChange([...drafts, blankDraft()])}
        hover={1.02}
        press={0.97}
        className={`${secondary} self-start`}
      >
        Add entry
      </PressButton>
    </div>
  );
}

function SummaryTab({ chat, draft, onChange }: { chat: Chat; draft: SummaryDraft; onChange: (d: SummaryDraft) => void }) {
  const summarize = useSummarize(chat.id);
  const save = useSaveSummary(chat.id);
  const [error, setError] = useState<string | null>(null);
  const busy = summarize.isPending || save.isPending;
  const edited = !draft.proposed && draft.text !== chat.summary;
  const total = chat.messages.length;

  async function generate() {
    setError(null);
    try {
      const res = await summarize.mutateAsync();
      onChange({ text: res.summary, upto: res.summary_upto, proposed: true });
    } catch (err) {
      setError(failure("summarize", err));
    }
  }

  async function persist(next: { summary: string; summary_upto: number }) {
    setError(null);
    try {
      const saved = await save.mutateAsync(next);
      onChange({ text: saved.summary, upto: saved.summary_upto, proposed: false });
    } catch (err) {
      setError(failure("save-summary", err));
    }
  }

  const status = draft.proposed
    ? `Not saved yet. This proposal would cover the first ${draft.upto} of ${total} messages. Edit it if you like, then Save to use it.`
    : edited
      ? "Unsaved edits."
      : chat.summary_upto > 0
        ? `Saved. Covers the first ${chat.summary_upto} of ${total} messages.`
        : "No summary yet.";

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="story-summary" className="text-[13px] font-medium">
        Story so far
      </label>
      <p className="text-[12px] text-muted">
        Replaces the older messages in what the model reads, which frees up context. Your chat itself is not changed.
      </p>
      <p
        role="status"
        className={`rounded-xl px-3 py-2 text-[13px] ${draft.proposed ? "bg-note-bg text-text" : "text-muted"}`}
      >
        {status}
      </p>
      <textarea
        id="story-summary"
        value={draft.text}
        maxLength={MAX_SUMMARY}
        rows={10}
        onChange={(e) => onChange({ ...draft, text: e.target.value })}
        className={`${field} min-h-40 resize-y ${draft.proposed ? "border-accent" : ""}`}
      />
      <div className="self-end">
        <Counter n={draft.text.length} max={MAX_SUMMARY} />
      </div>
      {error && <p role="alert" className="text-warn-bar">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <PressButton
          type="button"
          onClick={generate}
          disabled={busy || edited}
          title={edited ? "Save or discard your edits first" : undefined}
          hover={1.02}
          press={0.97}
          className={secondary}
        >
          {summarize.isPending ? "Generating…" : "Generate"}
        </PressButton>
        <PressButton
          type="button"
          onClick={() => persist({ summary: draft.text, summary_upto: draft.text.trim() ? draft.upto : 0 })}
          disabled={busy || !(draft.proposed || edited)}
          hover={1.02}
          press={0.97}
          className={primary}
        >
          {save.isPending ? "Saving…" : "Save"}
        </PressButton>
        {(draft.proposed || edited) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onChange({ text: chat.summary, upto: chat.summary_upto, proposed: false })}
            className={`rounded px-2 py-1 text-muted hover:text-text disabled:opacity-50 ${focus}`}
          >
            Discard changes
          </button>
        )}
        <button
          type="button"
          disabled={busy || (chat.summary_upto === 0 && !chat.summary && !draft.text)}
          onClick={() => persist({ summary: "", summary_upto: 0 })}
          className={`ml-auto rounded px-2 py-1 text-warn-bar disabled:opacity-50 ${focus}`}
        >
          Reset
        </button>
      </div>
    </div>
  );
}
