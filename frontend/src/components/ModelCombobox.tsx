import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { customCandidate, groupModels } from "../lib/modelOptions";

interface Props {
  value: string;
  models: readonly string[];
  onChange: (value: string) => void;
  className: string;
}

interface Option {
  value: string;
  custom: boolean;
}

export function ModelCombobox({ value, models, onChange, className }: Props) {
  const uid = useId();
  const listId = `${uid}-list`;
  const [open, setOpen] = useState(false);
  // null means "show everything": opening must not filter by the value already in the field.
  const [filter, setFilter] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const listRef = useRef<HTMLDivElement>(null);

  const query = filter ?? "";
  const groups = useMemo(() => groupModels(models, query), [models, query]);
  const custom = filter === null ? null : customCandidate(models, filter);

  const options = useMemo<Option[]>(() => {
    const list = groups.flatMap((g) => g.items.map((value) => ({ value, custom: false })));
    return custom ? [...list, { value: custom, custom: true }] : list;
  }, [groups, custom]);

  const optionId = (i: number) => `${uid}-opt-${i}`;

  useEffect(() => {
    if (open && active >= 0) listRef.current?.querySelector(`[id="${optionId(active)}"]`)?.scrollIntoView?.({ block: "nearest" });
    // optionId only depends on uid.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active]);

  function show() {
    setOpen(true);
  }

  function hide() {
    setOpen(false);
    setFilter(null);
    setActive(-1);
  }

  function pick(opt: Option) {
    onChange(opt.value);
    hide();
  }

  function move(step: number) {
    if (!open) show();
    if (options.length === 0) return;
    setActive((i) => (i < 0 ? (step > 0 ? 0 : options.length - 1) : (i + step + options.length) % options.length));
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      move(e.key === "ArrowDown" ? 1 : -1);
    } else if (e.key === "Enter" && open && options[active]) {
      e.preventDefault();
      pick(options[active]);
    } else if (e.key === "Escape" && open) {
      // Swallowed so only the list closes, not the surrounding modal.
      e.preventDefault();
      e.stopPropagation();
      hide();
    }
  }

  let index = -1;

  return (
    <div className="relative">
      <input
        role="combobox"
        aria-label="Model"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setFilter(e.target.value);
          setActive(-1);
          show();
        }}
        onFocus={show}
        onClick={show}
        onBlur={hide}
        onKeyDown={onKeyDown}
        autoComplete="off"
        spellCheck={false}
        className={`${className} w-full`}
      />
      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Models"
          // Keeps focus in the input so a click on an option does not blur-close the list first.
          onMouseDown={(e) => e.preventDefault()}
          className="absolute inset-x-0 top-full z-10 mt-1 max-h-60 overflow-y-auto rounded-xl border border-border bg-surface py-1 shadow-lift"
        >
          {groups.map((g, gi) => (
            <div key={g.vendor} role="group" aria-labelledby={`${uid}-g-${gi}`}>
              <div id={`${uid}-g-${gi}`} className="px-3 pb-0.5 pt-1.5 text-[12px] font-medium text-muted">
                {g.vendor}
              </div>
              {g.items.map((m) => {
                const i = ++index;
                return (
                  <Row key={m} id={optionId(i)} selected={m === value} active={i === active} onPick={() => pick({ value: m, custom: false })} onHover={() => setActive(i)}>
                    {m}
                  </Row>
                );
              })}
            </div>
          ))}
          {custom && (
            <Row id={optionId(++index)} selected={false} active={index === active} onPick={() => pick({ value: custom, custom: true })} onHover={() => setActive(index)}>
              Use &ldquo;{custom}&rdquo;
            </Row>
          )}
          {options.length === 0 && (
            <div className="px-3 py-1.5 text-[12px] text-muted">
              {models.length === 0 ? "No model list yet. Type a model ID, or use Test & fetch models." : "No match."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  id: string;
  selected: boolean;
  active: boolean;
  onPick: () => void;
  onHover: () => void;
  children: ReactNode;
}

function Row({ id, selected, active, onPick, onHover, children }: RowProps) {
  return (
    <div
      id={id}
      role="option"
      aria-selected={selected}
      onClick={onPick}
      onMouseMove={onHover}
      className={`cursor-pointer truncate px-3 py-1.5 ${active ? "bg-bg text-text" : "text-text"} ${selected ? "font-medium" : ""}`}
    >
      {children}
    </div>
  );
}
