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
      <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-soft transition-[border-color,box-shadow] duration-200 focus-within:border-accent/60 focus-within:shadow-lift">
        <PressButton
          type="button"
          aria-label="Search the web"
          aria-pressed={web}
          title="Search the web"
          onClick={() => setWeb((on) => !on)}
          className={`grid size-10 flex-none place-items-center rounded-xl transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            web ? "bg-accent/15 text-accent" : "text-muted hover:bg-bubble"
          }`}
        >
          <GlobeIcon />
        </PressButton>
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
          placeholder="Write a message…"
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
      <p className="mt-2 text-center text-xs text-muted">
        {web ? "Web search on · your message is sent to Tavily" : "Enter to send · Shift+Enter for a new line"}
      </p>
    </form>
  );
}
