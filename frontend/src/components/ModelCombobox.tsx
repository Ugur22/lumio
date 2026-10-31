import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions } from "@headlessui/react";
import { useId, useMemo, useState } from "react";
import { customCandidate, groupModels } from "../lib/modelOptions";

interface Props {
  value: string;
  models: readonly string[];
  onChange: (value: string) => void;
  className: string;
}

const optionClass = "cursor-pointer truncate px-3 py-1.5 text-text data-[focus]:bg-bg data-[selected]:font-medium";

export function ModelCombobox({ value, models, onChange, className }: Props) {
  const uid = useId();
  // Separate from `value`: opening must list every model, not just those matching the id already in the field.
  const [query, setQuery] = useState("");

  const groups = useMemo(() => groupModels(models, query), [models, query]);
  const custom = customCandidate(models, query);
  
  return (
    <Combobox
      value={value}
      immediate
      onChange={(next: string | null) => next !== null && onChange(next)}
      onClose={() => setQuery("")}
    >
      <div className="relative">
        <ComboboxInput
          aria-label="Model"
          displayValue={() => value}
          onChange={(e) => {
            onChange(e.target.value);
            setQuery(e.target.value);
          }}
          autoComplete="off"
          spellCheck={false}
          className={`${className} w-full`}
        />
        {/*
          No `anchor`: that portals the list to <body>, which sits outside the modal <dialog>'s top layer
          and is inert while the dialog is open. Rendering inline keeps it clickable.
        */}
        <ComboboxOptions
          modal={false}
          className="absolute inset-x-0 top-full z-10 mt-1 max-h-60 overflow-y-auto rounded-xl border border-border bg-surface py-1 shadow-lift"
        >
          {groups.map((g, gi) => (
            <div key={g.vendor} role="group" aria-labelledby={`${uid}-g-${gi}`}>
              <div id={`${uid}-g-${gi}`} className="px-3 pb-0.5 pt-1.5 text-[12px] font-medium text-muted">
                {g.vendor}
              </div>
              {g.items.map((m) => (
                <ComboboxOption key={m} value={m} className={optionClass}>
                  {m}
                </ComboboxOption>
              ))}
            </div>
          ))}
          {custom && (
            <ComboboxOption value={custom} className={optionClass}>
              Use &ldquo;{custom}&rdquo;
            </ComboboxOption>
          )}
          {groups.length === 0 && !custom && (
            <div className="px-3 py-1.5 text-[12px] text-muted">No model list yet. Type a model ID, or use Fetch models.</div>
          )}
        </ComboboxOptions>
      </div>
    </Combobox>
  );
}
