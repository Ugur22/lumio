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
  type ReactNode,
  type Ref,
} from "react";
import { continueList, shiftList, type Edit } from "../lib/lists";
import { ACCEPT_ATTR, prepareImage, rejectReason, type Attachment } from "../lib/images";
import { CloseIcon, GlobeIcon, PaperclipIcon, SendIcon, SparklesIcon, StopIcon } from "./icons";
import { Button, PressButton } from "./ui";

export interface ComposerHandle {
  focus: () => void;
  setText: (text: string) => void;
}

interface Props {
  ref?: Ref<ComposerHandle>;
  disabled: boolean;
  // Whether the active provider reads images; `providerName` is only used to explain why not.
  vision: boolean;
  providerName: string | null;
  // Whether the active provider has an image model; the Illustrate toggle only exists then.
  canIllustrate?: boolean;
  onSend: (text: string, attachments: Attachment[], web: boolean, illustrate: boolean) => void;
  onStop: () => void;
}

function fit(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

const toolBase =
  "flex h-8 flex-none items-center justify-center rounded-lg border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const toolOn = "border-accent/50 bg-accent/15 text-accent";
const toolOff = "border-transparent text-muted hover:bg-bg hover:text-text";

// Positioned against the (relative) toolbar rather than its own button, so every tip starts at the
// card's left edge and stays inside a 400px viewport however wide the toggles above have grown.
// has-[:focus-visible], not focus-within: a mouse click leaves focus on the button and would pin the tip open.
function Tip({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <div
      id={id}
      role="tooltip"
      className="pointer-events-none absolute bottom-full left-0 z-20 mb-2 w-[min(16rem,calc(100vw-3.5rem))] rounded-xl border border-border bg-surface px-3 py-2.5 text-[12px] leading-snug text-text opacity-0 shadow-lift transition-opacity duration-150 motion-reduce:transition-none group-has-[:focus-visible]/tip:opacity-100 group-hover/tip:opacity-100"
    >
      <strong className="block text-[13px] font-semibold">{title}</strong>
      <span className="mt-0.5 block">{children}</span>
    </div>
  );
}

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

export function Composer({ ref, disabled, vision, providerName, canIllustrate = false, onSend, onStop }: Props) {
  const [value, setValue] = useState("");
  const [web, setWeb] = useState(false);
  const [illustrate, setIllustrate] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [preparing, setPreparing] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
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
      setValue(text);
      input.current?.focus();
    },
  }), []);

  // Images picked on a vision model and then left behind by a provider switch can't be sent.
  const blocked = !vision && attachments.length > 0;
  const ready = (value.trim() !== "" || attachments.length > 0) && !disabled && !blocked && preparing === 0;
  const inList = /^\s*([-*]|\d+\.) +\S/.test(value.slice(value.lastIndexOf("\n") + 1));
  const unsupported = `${providerName ?? "This provider"} can't read images. Switch to a vision-capable provider, or turn on "Can read images" for it in Providers.`;

  async function addFiles(files: File[]) {
    if (files.length === 0) return;
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
    if ((!text && attachments.length === 0) || disabled || blocked || preparing > 0) return;
    const sending = attachments;
    setValue("");
    setAttachments([]);
    setNotice(null);
    // A leftover "on" from a provider without an image model must not reach the server (it answers 422).
    onSend(text, sending, web, canIllustrate && illustrate);
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
    void addFiles(Array.from(e.dataTransfer.files));
  }


  return (
    <form
      onSubmit={submit}
      onDragOver={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
      className="mx-auto w-full max-w-[760px] px-5 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] pt-3"
    >
      {(notice || blocked) && (
        <p role="status" className="mb-2 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
          {blocked
            ? `${providerName ?? "This provider"} can't read images. Remove them below or switch to a vision-capable provider.`
            : notice}
        </p>
      )}
      <div
        className={`relative rounded-2xl border bg-surface p-2 shadow-soft transition-[border-color,box-shadow] duration-200 focus-within:border-accent/60 focus-within:shadow-lift ${
          dragging ? "border-accent ring-2 ring-accent/40" : web ? "border-accent/50" : "border-border"
        }`}
      >
        {dragging && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-2xl bg-surface/90 text-[14px] font-medium text-accent"
          >
            {vision ? "Drop images to attach" : `${providerName ?? "This provider"} can't read images`}
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
        <textarea
          ref={input}
          rows={1}
          autoFocus
          aria-label="Message"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={
            attachments.length > 0
              ? "Ask something about the image…"
              : web
                ? "Ask anything — Lumio will search the web first…"
                : "Write a message…"
          }
          className="block max-h-[min(40vh,12rem)] w-full resize-none bg-transparent px-2.5 py-2 text-text outline-none placeholder:text-muted"
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="relative flex min-w-0 items-center gap-1">
            <div className="group/tip flex-none">
            <PressButton
              type="button"
              aria-pressed={web}
              aria-label="Search the web"
              aria-describedby="web-tip"
              onClick={() => setWeb((on) => !on)}
              hover={1.04}
              press={0.94}
              className={`${toolBase} ${web ? `${toolOn} gap-1.5 px-2.5` : `${toolOff} w-8`}`}
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
                  aria-label="Illustrate the reply"
                  aria-describedby="illustrate-tip"
                  onClick={() => setIllustrate((on) => !on)}
                  hover={1.04}
                  press={0.94}
                  className={`${toolBase} ${illustrate ? `${toolOn} gap-1.5 px-2.5` : `${toolOff} w-8`}`}
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
                aria-describedby="image-tip"
                onClick={() => (vision ? picker.current?.click() : setNotice(unsupported))}
                hover={vision ? 1.04 : 1}
                press={vision ? 0.94 : 1}
                className={`${toolBase} ${toolOff} w-8 ${vision ? "" : "cursor-not-allowed opacity-50"}`}
              >
                <PaperclipIcon />
              </PressButton>
              <Tip id="image-tip" title={vision ? "Attach images" : "Images not available"}>
                {vision
                  ? "Choose up to 4 images, or paste or drop them here. The model can look at them and answer questions about them."
                  : unsupported}
              </Tip>
            </div>
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
          {disabled ? (
            <PressButton
              type="button"
              aria-label="Stop"
              onClick={onStop}
              className="grid size-9 flex-none place-items-center rounded-xl bg-accent text-on-accent shadow-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <StopIcon />
            </PressButton>
          ) : (
            <PressButton
              type="submit"
              aria-label="Send"
              disabled={!ready}
              className={`grid size-9 flex-none place-items-center rounded-xl text-on-accent transition-[background-color,opacity] duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                ready ? "bg-accent shadow-soft" : "bg-muted opacity-40"
              }`}
            >
              <SendIcon />
            </PressButton>
          )}
        </div>
      </div>
      <p className={`mt-2 text-center text-xs ${web ? "text-accent" : "text-muted"}`}>
        {web
          ? "Web search on · your message is sent to Tavily"
          : inList
            ? "Enter adds an item · Enter on an empty item ends the list · Ctrl+Enter sends"
            : `Enter sends · Shift+Enter for a new line${vision ? " · Paste or drop images" : ""}`}
      </p>
    </form>
  );
}
