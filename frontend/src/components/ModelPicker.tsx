import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions, Popover, PopoverButton, PopoverPanel } from "@headlessui/react";
import { useId, useMemo, useState } from "react";
import { useProviderModels } from "../hooks/useProviderModels";
import { customCandidate, groupModels } from "../lib/modelOptions";
import { ChevronDownIcon } from "./icons";
import { fieldClass, focusRing } from "./ui/styles";

type Choice = { kind: "model"; model: string } | { kind: "default" } | { kind: "settings" };

const sameChoice = (a: Choice | null, b: Choice | null) =>
  a?.kind === b?.kind && (a?.kind !== "model" || a.model === (b as { model: string }).model);

const optionClass = "cursor-pointer truncate px-3 py-1.5 text-text data-[focus]:bg-bg data-[selected]:font-medium";

interface ChoicesProps {
  heading: string;
  // The model in force for this chat, marked as selected in the list.
  current: string;
  // The profile's model, offered as "use provider default" only when `showDefault`.
  defaultModel: string;
  showDefault: boolean;
  models: readonly string[];
  loading: boolean;
  // A failed model fetch or a failed save, shown inline.
  error: string | null;
  // null clears the override.
  onPick: (model: string | null) => void;
  onManage: () => void;
}

// Presentational so the list can be rendered without a query client or an open popover.
export function ModelChoices({ heading, current, defaultModel, showDefault, models, loading, error, onPick, onManage }: ChoicesProps) {
  const uid = useId();
  const [query, setQuery] = useState("");
  const groups = useMemo(() => groupModels(models, query), [models, query]);
  const custom = customCandidate(models, query);

  const choose = (c: Choice | null) => {
    if (!c) return;
    if (c.kind === "model") onPick(c.model);
    else if (c.kind === "default") onPick(null);
    else onManage();
  };

  return (
    <Combobox<Choice | null> value={{ kind: "model", model: current }} by={sameChoice} onChange={choose}>
      <p className="px-3 pb-1.5 pt-2.5 text-[12px] font-semibold text-muted">{heading}</p>
      <div className="px-2 pb-2">
        <ComboboxInput
          aria-label="Search or type a model ID"
          placeholder="Search or type a model ID"
          displayValue={() => query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          className={`${fieldClass} w-full py-1.5 text-[13px]`}
        />
      </div>
      {/* Rendered inline and always open: the panel itself is the popup, and no portal keeps focus handling simple. */}
      <ComboboxOptions static className="max-h-60 overflow-y-auto border-t border-border py-1 text-[13px]">
        {showDefault && (
          <ComboboxOption value={{ kind: "default" } as Choice} className={optionClass}>
            Use provider default ({defaultModel})
          </ComboboxOption>
        )}
        {loading && <div className="px-3 py-1.5 text-[12px] text-muted">Loading models…</div>}
        {error && (
          <div role="alert" className="px-3 py-1.5 text-[12px] text-warn-bar">
            {error}
          </div>
        )}
        {groups.map((g, gi) => (
          <div key={g.vendor} role="group" aria-labelledby={`${uid}-g-${gi}`}>
            <div id={`${uid}-g-${gi}`} className="px-3 pb-0.5 pt-1.5 text-[12px] font-medium text-muted">
              {g.vendor}
            </div>
            {g.items.map((m) => (
              <ComboboxOption key={m} value={{ kind: "model", model: m } as Choice} className={optionClass}>
                {m}
              </ComboboxOption>
            ))}
          </div>
        ))}
        {custom && (
          <ComboboxOption value={{ kind: "model", model: custom } as Choice} className={optionClass}>
            Use &ldquo;{custom}&rdquo;
          </ComboboxOption>
        )}
        {!loading && !error && groups.length === 0 && !custom && (
          <div className="px-3 py-1.5 text-[12px] text-muted">No models listed. Type a model ID.</div>
        )}
        <ComboboxOption value={{ kind: "settings" } as Choice} className={`${optionClass} mt-1 border-t border-border text-muted`}>
          Provider settings…
        </ComboboxOption>
      </ComboboxOptions>
    </Combobox>
  );
}

type Shared = Pick<ChoicesProps, "heading" | "current" | "defaultModel" | "showDefault" | "onManage">;

interface PanelProps extends Shared {
  profileId: string;
  saveError: string | null;
  // Rejecting keeps the popover open; the caller shows its own error through `saveError`.
  onPickWithWindows: (model: string | null, windows: Readonly<Record<string, number>>) => void | Promise<unknown>;
}

// Mounted only while the popover is open, which is what keeps the model list from being fetched up front.
function ModelPanel({ profileId, saveError, onPickWithWindows, onManage, close, ...rest }: PanelProps & { close: () => void }) {
  const { models, windows, error, isPending } = useProviderModels(profileId);
  const fetchError = error ? `Couldn't load models: ${error.message}` : null;
  return (
    <ModelChoices
      {...rest}
      models={models}
      loading={isPending}
      error={saveError ?? fetchError}
      onPick={(model) => void Promise.resolve(onPickWithWindows(model, windows)).then(close, () => undefined)}
      onManage={() => {
        close();
        onManage();
      }}
    />
  );
}

export function ModelPicker({ disabled, ...panel }: PanelProps & { disabled: boolean }) {
  return (
    <Popover className="relative min-w-0">
      <PopoverButton
        disabled={disabled}
        title="Choose the model for this chat"
        className={`flex min-w-0 max-w-[11rem] items-center gap-1 rounded-lg px-2 py-1 hover:bg-bubble hover:text-text disabled:opacity-60 max-[520px]:max-w-[6.5rem] ${focusRing}`}
      >
        <span className="truncate">{panel.current}</span>
        <ChevronDownIcon width={14} height={14} className="flex-none max-[520px]:hidden" />
      </PopoverButton>
      <PopoverPanel className="absolute right-0 top-full z-30 mt-1.5 w-[min(22rem,calc(100vw-1.5rem))] rounded-xl border border-border bg-surface shadow-lift">
        {({ close }) => <ModelPanel {...panel} close={close} />}
      </PopoverPanel>
    </Popover>
  );
}
