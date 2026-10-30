import { Listbox, ListboxButton, ListboxOption, ListboxOptions } from "@headlessui/react";
import { ChevronDownIcon } from "../icons";
import { cx, focusRing } from "./styles";

export interface SelectOption {
  value: string;
  label: string;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  // "field" matches a form input; "compact" is the smaller control used in the header.
  variant?: "field" | "compact";
  "aria-label"?: string;
  // Sizes the control, e.g. "max-w-[10rem]".
  className?: string;
}

const buttonVariants = {
  field: "rounded-xl border border-border bg-bg px-3 py-2",
  compact: "rounded-lg border border-border bg-surface px-3 py-1.5",
} as const;

// Inside a Headless Field, the Field's Label names the button; otherwise pass aria-label.
export function Select({ value, onChange, options, variant = "field", className, ...aria }: Props) {
  const current = options.find((o) => o.value === value);
  return (
    <Listbox value={value} onChange={onChange}>
      <div className={cx("relative", className)}>
        <ListboxButton
          {...aria}
          className={cx("flex w-full items-center justify-between gap-2 text-left text-text", buttonVariants[variant], focusRing)}
        >
          <span className="truncate">{current?.label ?? value}</span>
          <ChevronDownIcon width={14} height={14} aria-hidden="true" className="flex-none text-muted" />
        </ListboxButton>
        {/* Anchored, so the list escapes a scrolling dialog panel instead of being clipped by it. */}
        <ListboxOptions
          anchor="bottom start"
          modal={false}
          className="z-[60] max-h-60 w-max min-w-[var(--button-width)] max-w-[min(20rem,90vw)] overflow-y-auto rounded-xl border border-border bg-surface py-1 shadow-lift [--anchor-gap:4px] focus:outline-none"
        >
          {options.map((o) => (
            <ListboxOption
              key={o.value}
              value={o.value}
              className="cursor-pointer truncate px-3 py-1.5 text-text data-[focus]:bg-bg data-[selected]:font-medium"
            >
              {o.label}
            </ListboxOption>
          ))}
        </ListboxOptions>
      </div>
    </Listbox>
  );
}
