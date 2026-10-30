import { DialogTitle, Tab, TabGroup, TabList, TabPanel, TabPanels } from "@headlessui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { useChat } from "../hooks/useChats";
import { useSaveBehavior, useSaveStory, useSaveSummary, useSummarize } from "../hooks/useStory";
import {
  behaviorProblems,
  blankDraft,
  isBehaviorDirty,
  isStoryDirty,
  loreProblems,
  MAX_BIBLE,
  MAX_CONTENT,
  MAX_LORE,
  MAX_NAME,
  MAX_SUMMARY,
  MAX_SYSTEM_PROMPT,
  sanitizeNumber,
  stepNumber,
  BEHAVIOR_LIMITS,
  storyErrorText,
  toBehaviorBody,
  toBehaviorDraft,
  toBody,
  toDraft,
  type BehaviorDraft,
  type LoreDraft,
  type StoryAction,
} from "../lib/story";
import type { Chat, StoryBody } from "../types";
import { CloseIcon, TrashIcon } from "./icons";
import { Button, CheckboxField, Modal, PressButton, TextArea, TextAreaField, TextField, TextInput, focusRing } from "./ui";

export type StoryTab = "bible" | "lore" | "summary" | "behavior";

interface Props {
  open: boolean;
  chatId: string | null;
  // Which tab to land on each time the dialog opens.
  tab: StoryTab;
  onClose: () => void;
}


const TABS: { id: StoryTab; label: string }[] = [
  { id: "bible", label: "Bible" },
  { id: "lore", label: "Lore" },
  { id: "summary", label: "Summary" },
  { id: "behavior", label: "Behavior" },
];

const failure = (action: StoryAction, err: unknown) =>
  storyErrorText(action, err instanceof ApiError ? err.status : undefined, (err as Error).message);

export function StoryDialog({ open, chatId, tab, onClose }: Props) {
  // A ref as well as state: the close handler must see the latest value synchronously.
  const dirty = useRef(false);
  const [warn, setWarn] = useState(false);

  const onDirty = useCallback((d: boolean) => {
    dirty.current = d;
    if (!d) setWarn(false);
  }, []);

  function finish() {
    dirty.current = false;
    setWarn(false);
    onClose();
  }

  // Escape and backdrop clicks land here: with unsaved edits the dialog stays open and explains, instead of dropping them.
  function requestClose() {
    if (dirty.current) setWarn(true);
    else finish();
  }

  return (
    <Modal open={open && chatId !== null} onClose={requestClose} className="w-[min(94vw,40rem)]">
      {chatId && (
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
    </Modal>
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
        <div className="flex items-center justify-between gap-2">
          <DialogTitle as="h2" className="font-display text-lg font-semibold">Story</DialogTitle>
          <CloseButton onClick={rest.onClose} />
        </div>
        {error ? <p role="alert" className="text-warn-bar">{error.message}</p> : <p className="text-muted">Loading…</p>}
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
  const [behavior, setBehavior] = useState<BehaviorDraft>(() => toBehaviorDraft(chat));

  const storyDirty = isStoryDirty(chat, bible, lore);
  const summaryDirty = summary.proposed || summary.text !== chat.summary;
  const behaviorDirty = isBehaviorDirty(chat, behavior);
  const dirty = storyDirty || summaryDirty || behaviorDirty;

  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);

  const unsaved: Record<StoryTab, boolean> = {
    bible: bible !== chat.bible,
    lore: isStoryDirty(chat, chat.bible, lore),
    summary: summaryDirty,
    behavior: behaviorDirty,
  };

  return (
    <TabGroup
      selectedIndex={TABS.findIndex((t) => t.id === tab)}
      onChange={(i) => setTab(TABS[i]?.id ?? tab)}
      className="flex max-h-[min(90dvh,48rem)] flex-col"
    >
      <div className="flex flex-col gap-3 px-5 pt-5">
        <div className="flex items-center justify-between gap-2">
          <DialogTitle as="h2" className="font-display text-lg font-semibold">
            Story
          </DialogTitle>
          <CloseButton onClick={onClose} />
        </div>
        <TabList aria-label="Story sections" className="flex gap-1 border-b border-border">
          {TABS.map((t) => (
            <Tab
              key={t.id}
              className={`-mb-px rounded-t-lg border-b-2 border-transparent px-3 py-2 text-[13px] font-medium text-muted hover:text-text data-[selected]:border-accent data-[selected]:text-text ${focusRing}`}
            >
              {t.label}
              {unsaved[t.id] && (
                <>
                  <span aria-hidden="true" className="ml-1.5 inline-block size-1.5 rounded-full bg-caution align-middle" />
                  <span className="sr-only"> (unsaved changes)</span>
                </>
              )}
            </Tab>
          ))}
        </TabList>
      </div>

      <TabPanels className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <TabPanel>
          <BibleTab value={bible} onChange={setBible} />
        </TabPanel>
        <TabPanel>
          <LoreTab drafts={lore} onChange={setLore} />
        </TabPanel>
        <TabPanel>
          <SummaryTab chat={chat} draft={summary} onChange={setSummary} />
        </TabPanel>
        <TabPanel>
          <BehaviorTab draft={behavior} onChange={setBehavior} />
        </TabPanel>
      </TabPanels>

      {(tab !== "summary" || (warn && dirty)) && (
        <div className="flex flex-col gap-2 border-t border-border px-5 py-3">
          {warn && dirty && (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
              <span className="min-w-0 flex-1">You have unsaved changes. Save them first, or discard them to close.</span>
              <Button variant="bare" onClick={onKeepEditing} className="rounded px-2 py-1 font-medium">
                Keep editing
              </Button>
              <Button variant="bare" onClick={onDiscard} className="rounded px-2 py-1 font-medium underline">
                Discard and close
              </Button>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2">
            {tab === "behavior" && (
              <BehaviorActions
                chat={chat}
                draft={behavior}
                onRevert={() => setBehavior(toBehaviorDraft(chat))}
                onSaved={onDiscard}
              />
            )}
            {(tab === "bible" || tab === "lore") && (
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
          </div>
        </div>
      )}
    </TabGroup>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      variant="bare"
      aria-label="Close"
      onClick={onClick}
      className="-mr-1.5 grid size-8 place-items-center rounded-full text-muted hover:bg-bubble hover:text-text"
    >
      <CloseIcon width={18} height={18} />
    </Button>
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
      <span role="status" className="text-[12px] text-muted">
        {error ? "" : dirty ? (problems ? "Fix the highlighted entries to save." : "Unsaved changes") : save.isSuccess ? "Saved" : ""}
      </span>
      <Button onClick={onRevert} disabled={!dirty || save.isPending}>
        Revert
      </Button>
      <PressButton type="button" onClick={run} disabled={!dirty || problems} loading={save.isPending} hover={1.02} press={0.97} variant="primary">
        {save.isPending ? "Saving…" : "Save story"}
      </PressButton>
      {error && <p role="alert" className="basis-full text-warn-bar">{error}</p>}
    </>
  );
}

const NUMBER_FIELDS = [
  { key: "temperature", label: "Temperature", hint: "0 to 2. Lower is steadier, higher is wilder." },
  { key: "topP", label: "Top P", hint: "0 to 1. Lower keeps word choice safer." },
  { key: "frequencyPenalty", label: "Frequency penalty", hint: "-2 to 2. Higher repeats words less." },
  { key: "maxTokens", label: "Max reply tokens", hint: "Caps one reply's length. Reasoning models may count hidden thinking too." },
] as const;

function BehaviorActions({
  chat,
  draft,
  onRevert,
  onSaved,
}: {
  chat: Chat;
  draft: BehaviorDraft;
  onRevert: () => void;
  onSaved: () => void;
}) {
  const save = useSaveBehavior(chat.id);
  const [error, setError] = useState<string | null>(null);
  const hasProblems = Object.keys(behaviorProblems(draft)).length > 0;
  const dirty = isBehaviorDirty(chat, draft);

  async function run() {
    setError(null);
    try {
      await save.mutateAsync(toBehaviorBody(draft));
      onSaved();
    } catch (err) {
      setError(failure("save-behavior", err));
    }
  }

  return (
    <>
      <span role="status" className="text-[12px] text-muted">
        {error ? "" : dirty ? (hasProblems ? "Fix the highlighted fields to save." : "Unsaved changes") : ""}
      </span>
      <Button onClick={onRevert} disabled={!dirty || save.isPending}>
        Revert
      </Button>
      <PressButton type="button" onClick={run} disabled={!dirty || hasProblems} loading={save.isPending} hover={1.02} press={0.97} variant="primary">
        {save.isPending ? "Saving…" : "Save behavior"}
      </PressButton>
      {error && <p role="alert" className="basis-full text-warn-bar">{error}</p>}
    </>
  );
}

function BehaviorTab({ draft, onChange }: { draft: BehaviorDraft; onChange: (d: BehaviorDraft) => void }) {
  const problems = behaviorProblems(draft);

  return (
    <div className="flex flex-col gap-3">
      <TextAreaField
        label="Instructions for this chat"
        description="How the model should behave here: voice, style, rules. It leads the system message on every send, so a change applies from the next reply. Use the bible for facts about the story."
        value={draft.systemPrompt}
        maxLength={MAX_SYSTEM_PROMPT}
        rows={8}
        onChange={(e) => onChange({ ...draft, systemPrompt: e.target.value })}
        className="min-h-36"
        footer={<Counter n={draft.systemPrompt.length} max={MAX_SYSTEM_PROMPT} />}
      />

      <p className="text-[12px] text-muted">Leave a number blank to use the provider's default.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {NUMBER_FIELDS.map((f) => {
          const problem = problems[f.key];
          return (
            <TextField
              key={f.key}
              label={f.label}
              description={f.hint}
              error={problem}
              type="text"
              // The iOS decimal keypad has no minus sign, so the one field that takes negatives gets the full keyboard.
              inputMode={f.key === "frequencyPenalty" ? "text" : f.key === "maxTokens" ? "numeric" : "decimal"}
              autoComplete="off"
              spellCheck={false}
              value={draft[f.key]}
              role="spinbutton"
              aria-valuemin={BEHAVIOR_LIMITS[f.key].min}
              aria-valuemax={BEHAVIOR_LIMITS[f.key].max}
              aria-valuenow={draft[f.key].trim() && !problem ? Number(draft[f.key]) : undefined}
              onKeyDown={(e) => {
                if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
                e.preventDefault();
                onChange({ ...draft, [f.key]: stepNumber(draft[f.key], f.key, e.key === "ArrowUp" ? 1 : -1, e.shiftKey) });
              }}
              onChange={(e) => onChange({ ...draft, [f.key]: sanitizeNumber(e.target.value, f.key) })}
              fieldClassName="gap-1"
            />
          );
        })}
      </div>
    </div>
  );
}

function BibleTab({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <TextAreaField
      label="Story bible"
      description="Canon the model should always keep in mind: setting, characters, tone, rules. It is sent with every message."
      value={value}
      maxLength={MAX_BIBLE}
      rows={12}
      onChange={(e) => onChange(e.target.value)}
      className="min-h-48"
      footer={<Counter n={value.length} max={MAX_BIBLE} />}
    />
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
                <TextInput
                  surface
                  aria-label={`Name of entry ${i + 1}`}
                  value={d.name}
                  maxLength={MAX_NAME}
                  placeholder="Name"
                  onChange={(e) => update(d.id, { name: e.target.value })}
                  className="min-w-0 flex-1"
                />
                <CheckboxField compact label="Enabled" checked={d.enabled} onChange={(enabled) => update(d.id, { enabled })} className="flex-none" />
                <Button
                  variant="bare"
                  aria-label={`Delete ${d.name.trim() || `entry ${i + 1}`}`}
                  onClick={() => onChange(drafts.filter((x) => x.id !== d.id))}
                  className="flex-none rounded p-1.5 text-muted hover:text-warn-bar"
                >
                  <TrashIcon width={16} height={16} />
                </Button>
              </div>
              <TextInput
                surface
                aria-label={`Trigger keys for entry ${i + 1}`}
                value={d.keysText}
                placeholder="Trigger keys, comma separated"
                spellCheck={false}
                onChange={(e) => update(d.id, { keysText: e.target.value })}
              />
              <TextArea
                surface
                aria-label={`Content of entry ${i + 1}`}
                value={d.content}
                rows={3}
                placeholder="What the model should know when this comes up"
                onChange={(e) => update(d.id, { content: e.target.value })}
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
        variant="secondary"
        className="self-start"
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
      <TextAreaField
        label="Story so far"
        description="Replaces the older messages in what the model reads, which frees up context. Your chat itself is not changed."
        value={draft.text}
        maxLength={MAX_SUMMARY}
        rows={10}
        onChange={(e) => onChange({ ...draft, text: e.target.value })}
        className={`min-h-40 ${draft.proposed ? "border-accent" : ""}`}
        footer={<Counter n={draft.text.length} max={MAX_SUMMARY} />}
      >
        <p
          role="status"
          className={`rounded-xl px-3 py-2 text-[13px] ${draft.proposed ? "bg-note-bg text-text" : "text-muted"}`}
        >
          {status}
        </p>
      </TextAreaField>
      {error && <p role="alert" className="text-warn-bar">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <PressButton
          type="button"
          onClick={generate}
          disabled={busy || edited}
          loading={summarize.isPending}
          title={edited ? "Save or discard your edits first" : undefined}
          hover={1.02}
          press={0.97}
          variant="secondary"
        >
          {summarize.isPending ? "Generating…" : "Generate"}
        </PressButton>
        <PressButton
          type="button"
          onClick={() => persist({ summary: draft.text, summary_upto: draft.text.trim() ? draft.upto : 0 })}
          disabled={busy || !(draft.proposed || edited)}
          loading={save.isPending}
          hover={1.02}
          press={0.97}
          variant="primary"
        >
          {save.isPending ? "Saving…" : "Save"}
        </PressButton>
        {(draft.proposed || edited) && (
          <Button disabled={busy} onClick={() => onChange({ text: chat.summary, upto: chat.summary_upto, proposed: false })}>
            Discard changes
          </Button>
        )}
        <Button
          variant="danger"
          disabled={busy || (chat.summary_upto === 0 && !chat.summary && !draft.text)}
          onClick={() => persist({ summary: "", summary_upto: 0 })}
          className="ml-auto"
        >
          Reset
        </Button>
      </div>
    </div>
  );
}
