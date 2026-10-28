import { describe, expect, it } from "vitest";
import type { ContextInfo } from "../types";
import { contextLevel, formatTokens, meterView, partRows } from "./context";

const parts = { system: 300, bible: 1200, lore: 0, summary: 2500, history: 30000 };
const info = (over: Partial<ContextInfo>): ContextInfo => ({
  used: 34000,
  window: 128000,
  source: "provider",
  parts,
  ...over,
});

describe("formatTokens", () => {
  it.each([
    [0, "0"],
    [850, "850"],
    [1000, "1k"],
    [1500, "1.5k"],
    [9999, "10k"],
    [34000, "34k"],
    [128000, "128k"],
    [200000, "200k"],
    [1_000_000, "1M"],
    [1_500_000, "1.5M"],
    [-5, "0"],
  ])("%d -> %s", (n, out) => {
    expect(formatTokens(n)).toBe(out);
  });
});

describe("contextLevel", () => {
  it("switches to amber at 70% and red at 90%, inclusive", () => {
    expect(contextLevel(6999, 10000)).toBe("ok");
    expect(contextLevel(7000, 10000)).toBe("warn");
    expect(contextLevel(8999, 10000)).toBe("warn");
    expect(contextLevel(9000, 10000)).toBe("high");
    expect(contextLevel(12000, 10000)).toBe("high");
  });
});

describe("meterView", () => {
  it("formats the label and labels the source", () => {
    const v = meterView(info({}));
    expect(v).toMatchObject({ label: "34k / 128k", percent: 27, level: "ok", sourceLabel: "exact", suggestSummary: false });
    expect(meterView(info({ source: "estimate" }))?.sourceLabel).toBe("~estimate");
  });

  it("suggests summarizing from 70% up", () => {
    expect(meterView(info({ used: 90000 }))).toMatchObject({ level: "warn", suggestSummary: true });
    expect(meterView(info({ used: 120000 }))).toMatchObject({ level: "high", suggestSummary: true });
  });

  it("clamps the bar but not the number when the prompt overflows", () => {
    expect(meterView(info({ used: 150000 }))).toMatchObject({ percent: 117, barPercent: 100 });
  });

  it("has nothing to show without a window", () => {
    expect(meterView(info({ window: null }))).toBeNull();
  });
});

describe("partRows", () => {
  it("lists every part in prompt order", () => {
    expect(partRows(parts).map((r) => [r.label, r.tokens])).toEqual([
      ["Instructions", "300"],
      ["Story bible", "1.2k"],
      ["Lore", "0"],
      ["Summary", "2.5k"],
      ["Messages", "30k"],
    ]);
  });
});
