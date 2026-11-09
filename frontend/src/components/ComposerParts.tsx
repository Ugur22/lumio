import type { ReactNode } from "react";
import { bannerText, trialBanner, TRIAL_ENDED } from "../lib/trial";
import { GlobeIcon, PaperclipIcon, SparklesIcon } from "./icons";
import { BottomSheet, Button } from "./ui";

export const toolBase =
  "flex h-8 flex-none items-center justify-center rounded-lg border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
export const toolOn = "border-accent/50 bg-accent/15 text-accent";
export const toolOff = "border-transparent text-muted hover:bg-bg hover:text-text";

// Positioned against the (relative) toolbar rather than its own button, so every tip starts at the
// card's left edge and stays inside a 400px viewport however wide the toggles above have grown.
// has-[:focus-visible], not focus-within: a mouse click leaves focus on the button and would pin the tip open.
export function Tip({ id, title, children }: { id: string; title: string; children: ReactNode }) {
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

export const chip =
  "inline-flex h-8 items-center gap-1 rounded-full border border-accent/50 bg-accent/15 pl-3 pr-2 text-[13px] font-medium text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export const sheetRow =
  "flex min-h-[60px] w-full items-center gap-3.5 border-t border-border py-2 text-left text-[16px] leading-[1.3] focus-visible:rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

// Switch drawn from aria-pressed on the row, so the button stays the single source of truth.
export const sw =
  "relative h-7 w-[46px] flex-none rounded-full bg-border transition-colors duration-200 motion-reduce:transition-none after:absolute after:left-[3px] after:top-[3px] after:size-[22px] after:rounded-full after:bg-surface after:shadow-soft after:transition-transform after:duration-200 motion-reduce:after:transition-none group-aria-pressed/row:bg-accent group-aria-pressed/row:after:translate-x-[18px]";

export function SheetText({ title, hint }: { title: string; hint: string }) {
  return (
    <span className="flex min-w-0 flex-1 flex-col">
      {title}
      <small className="text-[13px] text-muted">{hint}</small>
    </span>
  );
}

export function TrialBannerView({ banner, onAddProvider }: { banner: NonNullable<ReturnType<typeof trialBanner>>; onAddProvider?: () => void }) {
  if (banner.kind === "ended") {
    return (
      <div role="status" className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
        <span className="min-w-0 flex-1">{TRIAL_ENDED}</span>
        {onAddProvider && (
          <Button variant="bare" onClick={onAddProvider} className="rounded px-2 py-1 font-medium underline">
            Open Providers
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="mb-1.5 flex">
      <span
        role="status"
        className={`inline-flex h-6 items-center rounded-full border px-2.5 text-[12px] ${
          banner.kind === "last" ? "border-warn-bar/40 bg-warn-bg text-warn-bar" : "border-border bg-surface text-muted"
        }`}
      >
        {bannerText(banner)}
      </span>
    </div>
  );
}

interface SheetProps {
  open: boolean;
  onClose: () => void;
  vision: boolean;
  providerName: string | null;
  unsupported: string;
  web: boolean;
  illustrate: boolean;
  canIllustrate: boolean;
  // Closes the sheet and opens the picker; only called when the provider reads images.
  onAttach: () => void;
  onWeb: () => void;
  onIllustrate: () => void;
}

export function AddSheet({ open, onClose, vision, providerName, unsupported, web, illustrate, canIllustrate, onAttach, onWeb, onIllustrate }: SheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} title="Add to message" eyebrow>
      <ul className="flex flex-col">
        <li>
          {/* aria-disabled, not disabled: it stays focusable so the reason is reachable. */}
          <button
            type="button"
            aria-disabled={!vision}
            onClick={() => vision && onAttach()}
            className={`${sheetRow} border-t-0 ${vision ? "" : "cursor-not-allowed opacity-50"}`}
          >
            <PaperclipIcon width={24} height={24} className="flex-none text-muted" />
            <SheetText title="Attach images" hint={vision ? `Up to 4. ${providerName ?? "This provider"} can read them.` : unsupported} />
          </button>
        </li>
        <li>
          <button type="button" aria-pressed={web} onClick={onWeb} className={`${sheetRow} group/row`}>
            <GlobeIcon width={24} height={24} className="flex-none text-muted" />
            <SheetText title="Search the web" hint="Looks it up first, then answers." />
            <span aria-hidden="true" className={sw} />
          </button>
        </li>
        {canIllustrate && (
          <li>
            <button type="button" aria-pressed={illustrate} onClick={onIllustrate} className={`${sheetRow} group/row`}>
              <SparklesIcon width={24} height={24} className="flex-none text-muted" />
              <SheetText title="Illustrate the reply" hint="Adds pictures between paragraphs." />
              <span aria-hidden="true" className={sw} />
            </button>
          </li>
        )}
      </ul>
    </BottomSheet>
  );
}
