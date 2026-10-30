import type { ContextInfo, ContextParts } from "../types";

export const WARN_AT = 0.7;
export const HIGH_AT = 0.9;

export type ContextLevel = "ok" | "warn" | "high";

// Compact token counts: 850, 1.5k, 34k, 128k, 1M.
export function formatTokens(n: number): string {
  const v = Math.max(0, Math.round(n));
  if (v < 1000) return String(v);
  if (v >= 999_500) return `${trim(v / 1_000_000)}M`;
  return `${v < 10_000 ? trim(v / 1000) : Math.round(v / 1000)}k`;
}

function trim(x: number): string {
  return x.toFixed(1).replace(/\.0$/, "");
}

export function contextLevel(used: number, window: number): ContextLevel {
  const ratio = used / window;
  return ratio >= HIGH_AT ? "high" : ratio >= WARN_AT ? "warn" : "ok";
}

export interface MeterView {
  label: string;
  // Whole percent for the label; the bar is clamped to 100 even when the prompt overflows.
  percent: number;
  barPercent: number;
  level: ContextLevel;
  sourceLabel: "exact" | "estimated";
  suggestSummary: boolean;
}

// Null when the window is unknown: there is nothing to measure against.
export function meterView(ctx: ContextInfo): MeterView | null {
  if (ctx.window === null || ctx.window <= 0) return null;
  const level = contextLevel(ctx.used, ctx.window);
  const percent = Math.round((ctx.used / ctx.window) * 100);
  return {
    label: `${formatTokens(ctx.used)} / ${formatTokens(ctx.window)}`,
    percent,
    barPercent: Math.min(100, percent),
    level,
    sourceLabel: ctx.source === "provider" ? "exact" : "estimated",
    suggestSummary: level !== "ok",
  };
}

const PART_LABELS: [keyof ContextParts, string][] = [
  ["system", "Instructions"],
  ["bible", "Story bible"],
  ["lore", "Lore"],
  ["summary", "Summary"],
  ["history", "Messages"],
];

export function partRows(parts: ContextParts): { key: keyof ContextParts; label: string; tokens: string }[] {
  return PART_LABELS.map(([key, label]) => ({ key, label, tokens: formatTokens(parts[key]) }));
}
