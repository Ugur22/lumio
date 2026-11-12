import type { OrbState } from "thinking-orbs";
import type { SourceRef } from "../types";

// What the status line says while no reply text has been shown yet.
export type Phase = "waiting" | "still" | "thinking" | "searching" | "reading" | "writing";

// The counter stays hidden for the first seconds so a quick reply never flashes a number.
export const COUNTER_AFTER_MS = 3000;
// With no signal for this long the label changes, so a slow model never looks frozen.
export const STILL_AFTER_MS = 6000;

export interface PhaseInput {
  elapsedMs: number;
  reasoning: string;
  query: string | null;
  sources: readonly SourceRef[];
  // Reply text has been shown.
  hasText: boolean;
}

export const hasReasoning = (reasoning: string) => reasoning.trim().length > 0;

// The later the stage, the more it wins: text over sources over a query over reasoning over silence.
export function phaseOf({ elapsedMs, reasoning, query, sources, hasText }: PhaseInput): Phase {
  if (hasText) return "writing";
  if (sources.length > 0) return "reading";
  if (query?.trim()) return "searching";
  if (hasReasoning(reasoning)) return "thinking";
  return elapsedMs >= STILL_AFTER_MS ? "still" : "waiting";
}

const LABEL: Record<Exclude<Phase, "writing">, string> = {
  waiting: "Thinking",
  still: "Still thinking",
  thinking: "Thinking",
  searching: "Searching the web",
  reading: "Reading sources",
};

const ORB: Record<Exclude<Phase, "writing">, OrbState> = {
  waiting: "connecting",
  still: "breathing",
  thinking: "solving",
  searching: "searching",
  reading: "working",
};

export const orbStateOf = (phase: Exclude<Phase, "writing">): OrbState => ORB[phase];

export const labelOf = (phase: Exclude<Phase, "writing">) => LABEL[phase];

export const counterText = (elapsedMs: number) =>
  elapsedMs >= COUNTER_AFTER_MS ? `· ${Math.floor(elapsedMs / 1000)}s` : "";

// Hosts of the pages that were read, as plain text for chips. Page URLs come from the web, so only http(s) ones count.
export function sourceDomains(sources: readonly SourceRef[]): string[] {
  const hosts = new Set<string>();
  for (const { url } of sources) {
    if (!/^https?:\/\//i.test(url)) continue;
    try {
      hosts.add(new URL(url).host.replace(/^www\./, ""));
    } catch {
      // A malformed URL has no domain to show.
    }
  }
  return [...hosts];
}

// The reasoning of a finished turn, folded under "Thought for Ns".
export interface Thought {
  text: string;
  seconds: number;
}

export function thoughtOf(reasoning: string, startedAt: number | null, textAt: number | null): Thought | null {
  if (!hasReasoning(reasoning) || startedAt === null || textAt === null) return null;
  return { text: reasoning, seconds: Math.max(1, Math.round((textAt - startedAt) / 1000)) };
}
