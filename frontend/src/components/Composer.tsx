import { useEffect, useImperativeHandle, useRef, useState, type FormEvent, type KeyboardEvent, type Ref } from "react";
import { GlobeIcon, SendIcon, StopIcon } from "./icons";
import { PressButton } from "./PressButton";

export interface ComposerHandle {
  focus: () => void;
  setText: (text: string) => void;
}

interface Props {
  ref?: Ref<ComposerHandle>;
  disabled: boolean;
  onSend: (text: string, web: boolean) => void;
  onStop: () => void;
}

function fit(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

export function Composer({ ref, disabled, onSend, onStop }: Props) {
  const [value, setValue] = useState("");
  const [web, setWeb] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, [disabled]);

  useImperativeHandle(ref, () => ({
    focus: () => input.current?.focus(),
    setText: (text) => {
      setValue(text);
      input.current?.focus();
      // Wait for React to commit the new value so scrollHeight is correct.
      requestAnimationFrame(() => fit(input.current));
    },
  }), []);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = value.trim();
    if (!text || disabled) return;
    setValue("");
    // Reset after React clears the value so scrollHeight shrinks back.
    requestAnimationFrame(() => fit(input.current));
    onSend(text, web);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing keeps IME users from sending mid-composition.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  const ready = value.trim() !== "" && !disabled;

  return (
    <form
      onSubmit={submit}
      className="mx-auto w-full max-w-[720px] px-5 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] pt-3"
    >
      <div
        className={`flex items-end gap-2 rounded-2xl border bg-surface p-2 shadow-soft transition-[border-color,box-shadow] duration-200 focus-within:border-accent/60 focus-within:shadow-lift ${
          web ? "border-accent/50" : "border-border"
        }`}
      >
        <div className="group relative flex-none">
          <PressButton
            type="button"
            aria-pressed={web}
            aria-label="Search the web"
            aria-describedby="web-tip"
            onClick={() => setWeb((on) => !on)}
            hover={1.03}
            press={0.96}
            className={`flex h-10 items-center justify-center gap-1.5 rounded-xl border px-2.5 text-[13px] font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              web ? "border-accent/50 bg-accent/15 text-accent" : "border-border bg-bg text-muted hover:text-text"
            }`}
          >
            <GlobeIcon />
            <span className="hidden min-[480px]:inline">{web ? "Web on" : "Web"}</span>
            {web && <span aria-hidden="true" className="size-1.5 rounded-full bg-accent min-[480px]:hidden" />}
          </PressButton>
          {/* has-[:focus-visible], not focus-within: a mouse click leaves focus on the button and would pin the tip open. */}
          <div
            id="web-tip"
            role="tooltip"
            className="pointer-events-none absolute bottom-full left-0 z-20 mb-2.5 w-[min(15rem,calc(100vw-2.5rem))] rounded-xl border border-border bg-surface px-3 py-2.5 text-[12px] leading-snug text-text opacity-0 shadow-lift transition-opacity duration-150 group-has-[:focus-visible]:opacity-100 group-hover:opacity-100 group-hover:delay-300"
          >
            <strong className="block text-[13px] font-semibold">{web ? "Web search is on" : "Search the web"}</strong>
            <span className="mt-0.5 block">
              {web
                ? "Each message is looked up online first. Click to turn it off."
                : "Looks your message up online and reads the top results before answering."}
            </span>
            <span className="mt-1.5 block text-muted">Links you paste are always read.</span>
          </div>
        </div>
        <textarea
          ref={input}
          rows={1}
          autoFocus
          aria-label="Message"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            fit(e.target);
          }}
          onKeyDown={onKeyDown}
          placeholder={web ? "Ask anything — Lumio will search the web first…" : "Write a message…"}
          className="max-h-[40vh] flex-1 resize-none bg-transparent px-2.5 py-2 text-text outline-none placeholder:text-muted"
        />
        {disabled ? (
          <PressButton
            type="button"
            aria-label="Stop"
            onClick={onStop}
            className="grid size-10 flex-none place-items-center rounded-xl bg-accent text-white shadow-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <StopIcon />
          </PressButton>
        ) : (
        <PressButton
          type="submit"
          aria-label="Send"
          disabled={!ready}
          className={`grid size-10 flex-none place-items-center rounded-xl text-white transition-[background-color,opacity] duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            ready ? "bg-accent shadow-soft" : "bg-muted opacity-40"
          }`}
        >
          <SendIcon />
        </PressButton>
        )}
      </div>
      <p className={`mt-2 text-center text-xs ${web ? "text-accent" : "text-muted"}`}>
        {web ? "Web search on · your message is sent to Tavily" : "Enter to send · Shift+Enter for a new line"}
      </p>
    </form>
  );
}
