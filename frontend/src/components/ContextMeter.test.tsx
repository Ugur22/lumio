import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ContextInfo } from "../types";
import { ContextMeter } from "./ContextMeter";

const parts = { system: 300, bible: 1200, lore: 0, summary: 0, history: 30000 };
const info = (over: Partial<ContextInfo>): ContextInfo => ({ used: 34000, window: 128000, source: "provider", parts, ...over });
const html = (context: ContextInfo | undefined) =>
  renderToStaticMarkup(<ContextMeter context={context} onSetWindow={() => undefined} onSummarize={() => undefined} />);

describe("ContextMeter", () => {
  it("shows used / window, the source and the breakdown", () => {
    const out = html(info({}));
    expect(out).toContain("34k / 128k");
    expect(out).toContain("exact");
    expect(out).toContain("Story bible");
    expect(out).toContain('aria-valuenow="27"');
    expect(out).not.toContain("Summarize older chapters");
  });

  it("marks estimates", () => {
    expect(html(info({ source: "estimate" }))).toContain("~estimate");
  });

  it("goes amber then red and offers to summarize from 70%", () => {
    const warn = html(info({ used: 90000 }));
    expect(warn).toContain("bg-caution");
    expect(warn).toContain("Summarize older chapters");
    expect(html(info({ used: 120000 }))).toContain("bg-warn-bar");
  });

  it("falls back to a Set context size hint without a window", () => {
    const out = html(info({ window: null }));
    expect(out).toContain("Set context size");
    expect(out).not.toContain("role=\"meter\"");
  });

  it("renders nothing before the first measurement", () => {
    expect(html(undefined)).toBe("");
  });
});
