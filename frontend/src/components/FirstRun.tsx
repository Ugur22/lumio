import type { ReactNode } from "react";
import { useEmptyKind } from "../hooks/useEmptyKind";
import { EMPTY_COPY, KEY_NOTE, PROVIDER_EXPLAINER, STEPS, type EmptyKind } from "../lib/emptyProviders";
import { PlugIcon } from "./icons";
import { Button } from "./ui";

// Stands in for the blank-chat welcome while there is no provider to send to; `fallback` is the normal welcome.
export function FirstRun({ onManage, fallback }: { onManage: () => void; fallback: ReactNode }) {
  const kind = useEmptyKind();
  return kind ? <Onboarding kind={kind} onManage={onManage} /> : fallback;
}

export function Onboarding({ kind, onManage }: { kind: EmptyKind; onManage: () => void }) {
  const { title, body } = EMPTY_COPY[kind];
  return (
    <div className="mb-2 flex flex-col items-center gap-3.5 px-1 text-center min-[721px]:items-start min-[721px]:text-left">
      <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-2xl border border-border bg-surface text-accent">
        <PlugIcon size={26} />
      </span>
      <h2 className="font-display text-2xl font-semibold leading-tight min-[721px]:text-[2.1rem]">{title}</h2>
      <p className="text-muted">{body}</p>
      {kind === "new" && (
        <>
          <p className="text-muted">{PROVIDER_EXPLAINER}</p>
          <ol aria-label="How to connect" className="m-0 flex w-full list-none flex-col gap-2.5 rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm">
            {STEPS.map((step, i) => (
              <li key={step} className="flex items-center gap-3">
                <span aria-hidden="true" className="flex size-6 flex-none items-center justify-center rounded-full bg-bubble text-xs font-semibold text-accent">
                  {i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="text-sm text-muted">{KEY_NOTE}</p>
      <Button variant="primary" onClick={onManage} className="rounded-xl px-5 py-2.5 max-[720px]:w-full">
        Add a provider
      </Button>
    </div>
  );
}
