import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type Ref,
} from "react";
import { continueList, shiftList, type Edit } from "../lib/lists";
import { ACCEPT_ATTR, prepareImage, rejectReason, type Attachment } from "../lib/images";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { trialBanner } from "../lib/trial";
import { CloseIcon, GlobeIcon, PaperclipIcon, PlusIcon, SendIcon, SparklesIcon, StopIcon } from "./icons";
import { AddSheet, chip, Tip, toolBase, toolOff, toolOn, TrialBannerView } from "./ComposerParts";
import type { TrialStatus } from "../types";
import { Button, PressButton } from "./ui";

export interface ComposerHandle {
  focus: () => void;
  setText: (text: string) => void;
  enableWeb: () => void;
  // Opens the image picker, or shows the unsupported notice when the provider can't read images.
  openPicker: () => void;
}

interface Props {
  ref?: Ref<ComposerHandle>;
  disabled: boolean;
  // Whether the active provider reads images; `providerName` is only used to explain why not.
  vision: boolean;
  providerName: string | null;
  // Whether the active provider has an image model; the Illustrate toggle only exists then.
  canIllustrate?: boolean;
  // The active provider is the free trial's: no images, web search or illustrations, and the count shows above the card.
  managed?: boolean;
  trial?: TrialStatus;
  // Opens Providers; offered when the trial has ended.
  onAddProvider?: () => void;
  // No provider to send to (the first-run onboarding is showing): nothing can be typed, attached or sent.
  locked?: boolean;
  onSend: (text: string, attachments: Attachment[], web: boolean, illustrate: boolean) => void;
  onStop: () => void;
}

function fit(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}


const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

export function Composer({ ref, disabled, vision, providerName, canIllustrate = false, managed = false, trial, locked = false, onAddProvider, onSend, onStop }: Props) {
  const [value, setValue] = useState("");
  const [web, setWeb] = useState(false);
  const [illustrate, setIllustrate] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [preparing, setPreparing] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const phone = useMediaQuery("(max-width: 720px)");
  const input = useRef<HTMLTextAreaElement>(null);
  const caret = useRef<number | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  // Mirrors state so addFiles can count images added earlier in the same batch.
  const count = useRef(0);
  const latest = useRef<Attachment[]>([]);

  latest.current = attachments;
  count.current = attachments.length + preparing;

  useEffect(() => {
    input.current?.focus();
  }, [disabled]);

  // Fitting after every committed value covers typing, setText and the reset after send alike.
  useLayoutEffect(() => {
    const el = input.current;
    fit(el);
    if (el && caret.current !== null) el.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  }, [value]);

  // Thumbnails still waiting in the composer are ours to free; sent ones belong to the stream store.
  useEffect(() => () => latest.current.forEach((a) => URL.revokeObjectURL(a.preview)), []);

  useImperativeHandle(ref, () => ({
    focus: () => input.current?.focus(),
    setText: (text) => {
      if (locked) return;
      caret.current = text.length;
      setValue(text);
      input.current?.focus();
    },
    enableWeb: () => setWeb(!managed && !locked),
    openPicker,
  }));

  // Images picked on a vision model and then left behind by a provider switch can't be sent.
  const blocked = !vision && attachments.length > 0;
  const banner = managed ? trialBanner(trial) : null;
  // Sending would only bounce off a 402, so the button says no before the request does.
  const ended = banner?.kind === "ended";
  // The toggles are hidden for the trial, so a leftover "on" from another provider must neither show nor be sent.
  const webOn = web && !managed;
  const ready = (value.trim() !== "" || attachments.length > 0) && !disabled && !locked && !blocked && !ended && preparing === 0;
  const inList = /^\s*([-*]|\d+\.) +\S/.test(value.slice(value.lastIndexOf("\n") + 1));
  const unsupported = managed
    ? "Images are not part of the free trial. Add your own provider to use them."
    : `${providerName ?? "This provider"} can't read images. Switch to a vision-capable provider, or turn on "Can read images" for it in Providers.`;

  function openPicker() {
    if (locked) return;
    if (vision) picker.current?.click();
    else setNotice(unsupported);
  }

  async function addFiles(files: File[]) {
    if (files.length === 0 || locked) return;
    if (!vision) {
      setNotice(unsupported);
      return;
    }
    setNotice(null);
    for (const file of files) {
      const reason = rejectReason(file, count.current);
      if (reason) {
        setNotice(reason);
        continue;
      }
      count.current += 1;
      setPreparing((n) => n + 1);
      try {
        const attachment = await prepareImage(file);
        setAttachments((list) => [...list, attachment]);
      } catch (err) {
        count.current -= 1;
        setNotice((err as Error).message);
      } finally {
        setPreparing((n) => n - 1);
      }
    }
  }

  function remove(id: string) {
    const gone = attachments.find((a) => a.id === id);
    if (gone) URL.revokeObjectURL(gone.preview);
    setAttachments((list) => list.filter((a) => a.id !== id));
    setNotice(null);
  }

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = value.trim();
    if ((!text && attachments.length === 0) || disabled || locked || blocked || ended || preparing > 0) return;
    const sending = attachments;
    setValue("");
    setAttachments([]);
    setNotice(null);
    // A leftover "on" from a provider without an image model must not reach the server (it answers 422).
    onSend(text, sending, webOn, canIllustrate && !managed && illustrate);
  }

  function apply(e: KeyboardEvent<HTMLTextAreaElement>, edit: Edit | null) {
    if (!edit) return false;
    e.preventDefault();
    caret.current = edit.caret;
    setValue(edit.value);
    return true;
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing keeps IME users from sending mid-composition.
    if (e.nativeEvent.isComposing) return;
    const el = e.currentTarget;
    const collapsed = el.selectionStart === el.selectionEnd;
    if (e.key === "Tab" && collapsed && !e.ctrlKey && !e.metaKey && !e.altKey) {
      apply(e, shiftList(el.value, el.selectionStart, e.shiftKey));
      return;
    }
    if (e.key !== "Enter" || e.shiftKey) return;
    // Ctrl/Cmd+Enter always sends, even from inside a list.
    const send = e.ctrlKey || e.metaKey;
    if (!send && collapsed && apply(e, continueList(el.value, el.selectionStart))) return;
    e.preventDefault();
    submit();
  }

  function onPaste(e: ClipboardEvent) {
    const images = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
    if (images.length === 0) return; // plain text paste proceeds as usual
    e.preventDefault();
    void addFiles(images);
  }

  function onDrop(e: DragEvent) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    setDragging(false);
    if (locked) return;
    void addFiles(Array.from(e.dataTransfer.files));
  }

  const sendClass = "grid flex-none place-items-center text-on-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
  const size = phone ? "size-10 rounded-full" : "size-9 rounded-xl";
  const sendButton = disabled ? (
    <PressButton type="button" aria-label="Stop" onClick={onStop} className={`${sendClass} ${size} bg-warn-bar shadow-soft`}>
      <StopIcon />
    </PressButton>
  ) : (
    <PressButton
      type="submit"
      aria-label="Send"
      disabled={!ready}
      className={`${sendClass} ${size} transition-[background-color,opacity] duration-200 motion-reduce:transition-none ${ready ? "bg-accent shadow-soft" : "bg-muted opacity-40"}`}
    >
      <SendIcon />
    </PressButton>
  );

  return (
    <form
      onSubmit={submit}
      onDragOver={(e) => {
        if (!hasFiles(e) || locked) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
      className="mx-auto w-full max-w-[760px] px-3 pb-[max(0.75rem,env(safe-area-inset-bottom,0px))] [:root[data-keyboard=open]_&]:pb-2 pt-2 min-[721px]:px-5 min-[721px]:pt-3"
    >
      {banner && <TrialBannerView banner={banner} onAddProvider={onAddProvider} />}
      {(notice || blocked) && (
        <p role="status" className="mb-2 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
          {blocked
            ? `${providerName ?? "This provider"} can't read images. Remove them below or switch to a vision-capable provider.`
            : notice}
        </p>
      )}
      <div
        className={`relative border bg-surface shadow-soft focus-within:border-accent/60 focus-within:shadow-lift ${
          phone
            ? "min-h-[52px] rounded-[26px] p-1.5" // no border/shadow transition here: it repaints every frame while the keyboard opens
            : "rounded-2xl p-2 transition-[border-color,box-shadow] duration-200"
        } ${dragging ? "border-accent ring-2 ring-accent/40" : webOn ? "border-accent/50" : "border-border"}`}
      >
        {dragging && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-[inherit] bg-surface/90 text-[14px] font-medium text-accent"
          >
            {vision ? "Drop images to attach" : managed ? "Images are not part of the free trial" : `${providerName ?? "This provider"} can't read images`}
          </div>
        )}
        {(attachments.length > 0 || preparing > 0) && (
          <ul className="mb-2 flex flex-wrap gap-2 px-1 pt-1" aria-label="Attached images">
            {attachments.map((a, i) => (
              <li key={a.id} className="group/thumb relative">
                <img
                  src={a.preview}
                  alt={`Attached image ${i + 1}`}
                  className="size-16 rounded-lg border border-border object-cover"
                />
                <Button variant="bare"
                  type="button"
                  aria-label={`Remove image ${i + 1}`}
                  onClick={() => remove(a.id)}
                  className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-border bg-surface text-muted shadow-soft hover:text-text"
                >
                  <CloseIcon width={11} height={11} />
                </Button>
              </li>
            ))}
            {Array.from({ length: preparing }, (_, i) => (
              <li
                key={`prep-${i}`}
                role="status"
                aria-label="Preparing image"
                className="size-16 animate-pulse rounded-lg border border-border bg-bubble"
              />
            ))}
          </ul>
        )}
        <div className={phone ? "flex items-end gap-1" : undefined}>
          {phone && !managed && (
            <PressButton
              type="button"
              aria-label="Add to message"
              aria-haspopup="dialog"
              disabled={locked}
              onClick={() => setSheet(true)}
              className="grid size-10 flex-none place-items-center rounded-full text-muted hover:bg-bg hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <PlusIcon />
            </PressButton>
          )}
          <div className={phone ? "flex min-w-0 flex-1 flex-wrap items-center gap-1.5 px-1 py-[7px]" : undefined}>
            {phone && webOn && (
              <button type="button" aria-label="Turn off web search" onClick={() => setWeb(false)} className={chip}>
                Web on <CloseIcon width={12} height={12} />
              </button>
            )}
            {phone && !managed && canIllustrate && illustrate && (
              <button type="button" aria-label="Turn off illustrate" onClick={() => setIllustrate(false)} className={chip}>
                Illustrate on <CloseIcon width={12} height={12} />
              </button>
            )}
            <textarea
              ref={input}
              rows={1}
              autoFocus
              aria-label="Message"
              disabled={locked}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
              }}
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              placeholder={
                locked
                  ? "Add a provider to start chatting"
                  : attachments.length > 0
                  ? "Ask something about the image…"
                  : webOn
                    ? "Ask anything — Lumio will search the web first…"
                    : "Write a message…"
              }
              className={`max-h-[min(40vh,12rem)] resize-none bg-transparent text-[16px] text-text outline-none placeholder:text-muted disabled:cursor-not-allowed ${
                phone ? "min-w-[6rem] flex-1 px-1 py-0.5 leading-[1.35]" : "block w-full px-2.5 py-2 text-[length:inherit]"
              }`}
            />
          </div>
          {phone && sendButton}
        </div>
        {!phone && (
          <div className="mt-1 flex items-center justify-between gap-2">
            <div className="relative flex min-w-0 items-center gap-1">
              {!managed && (
              <>
              <div className="group/tip flex-none">
                <PressButton
                  type="button"
                  aria-pressed={web}
                  disabled={locked}
                  aria-label="Search the web"
                  aria-describedby="web-tip"
                  onClick={() => setWeb((on) => !on)}
                  hover={1.04}
                  press={0.94}
                  className={`${toolBase} disabled:cursor-not-allowed disabled:opacity-50 ${web ? `${toolOn} gap-1.5 px-2.5` : `${toolOff} w-8`}`}
                >
                  <GlobeIcon />
                  {web && <span className="text-[13px] font-medium">Web on</span>}
                </PressButton>
                <Tip id="web-tip" title={web ? "Web search is on" : "Search the web"}>
                  {web
                    ? "Each message is looked up online first. Click to turn it off."
                    : "Looks your message up online and reads the top results before answering. Links you paste are always read."}
                </Tip>
              </div>
              {canIllustrate && (
                <div className="group/tip flex-none">
                  <PressButton
                    type="button"
                    aria-pressed={illustrate}
                    disabled={locked}
                    aria-label="Illustrate the reply"
                    aria-describedby="illustrate-tip"
                    onClick={() => setIllustrate((on) => !on)}
                    hover={1.04}
                    press={0.94}
                    className={`${toolBase} disabled:cursor-not-allowed disabled:opacity-50 ${illustrate ? `${toolOn} gap-1.5 px-2.5` : `${toolOff} w-8`}`}
                  >
                    <SparklesIcon />
                    {illustrate && <span className="text-[13px] font-medium">Illustrate on</span>}
                  </PressButton>
                  <Tip id="illustrate-tip" title={illustrate ? "Illustrations are on" : "Illustrate the reply"}>
                    {illustrate
                      ? "Pictures are added between the paragraphs of each reply. Click to turn it off."
                      : "Adds pictures between the paragraphs of the reply. Needs an image model, and each picture is a separate image request to your provider."}
                  </Tip>
                </div>
              )}
              <div className="group/tip flex-none">
                {/* aria-disabled, not disabled: it must stay focusable so keyboard users can read why it is off. */}
                <PressButton
                  type="button"
                  aria-label="Attach images"
                  aria-disabled={!vision}
                  disabled={locked}
                  aria-describedby="image-tip"
                  onClick={openPicker}
                  hover={vision ? 1.04 : 1}
                  press={vision ? 0.94 : 1}
                  className={`${toolBase} ${toolOff} w-8 disabled:cursor-not-allowed disabled:opacity-50 ${vision ? "" : "cursor-not-allowed opacity-50"}`}
                >
                  <PaperclipIcon />
                </PressButton>
                <Tip id="image-tip" title={vision ? "Attach images" : "Images not available"}>
                  {vision
                    ? "Choose up to 4 images, or paste or drop them here. The model can look at them and answer questions about them."
                    : unsupported}
                </Tip>
              </div>
              </>
              )}
            </div>
            {sendButton}
          </div>
        )}
        <input
          ref={picker}
          type="file"
          accept={ACCEPT_ATTR}
          multiple
          hidden
          onChange={(e) => {
            void addFiles(Array.from(e.target.files ?? []));
            // Cleared so picking the same file again still fires onChange.
            e.target.value = "";
          }}
        />
      </div>
      <AddSheet
        open={phone && !managed && sheet}
        onClose={() => setSheet(false)}
        vision={vision}
        providerName={providerName}
        unsupported={unsupported}
        web={web}
        illustrate={illustrate}
        canIllustrate={canIllustrate}
        onWeb={() => setWeb((on) => !on)}
        onIllustrate={() => setIllustrate((on) => !on)}
        onAttach={() => {
          setSheet(false);
          openPicker();
        }}
      />
      <p className={`mt-2 text-center text-xs [@media(pointer:coarse)]:hidden ${webOn ? "text-accent" : "text-muted"}`}>
        {webOn
          ? "Web search on · your message is sent to Tavily"
          : inList
            ? "Enter adds an item · Enter on an empty item ends the list · Ctrl+Enter sends"
            : `Enter sends · Shift+Enter for a new line${vision ? " · Paste or drop images" : ""}`}
      </p>
    </form>
  );
}
