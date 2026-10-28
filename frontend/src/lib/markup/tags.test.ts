import { describe, expect, it } from "vitest";
import { applyTags } from "./tags";

describe("applyTags", () => {
  it("turns key into mark and note/warn into asides", () => {
    expect(applyTags("a [[key]]b[[/key]]")).toBe('a <mark class="hl-key">b</mark>');
    expect(applyTags("[[note]]n[[/note]]")).toBe('<aside class="hl-note">\n\nn\n\n</aside>');
    expect(applyTags("[[warn]]w[[/warn]]")).toBe('<aside class="hl-warn">\n\nw\n\n</aside>');
  });

  it("keeps markdown inside the tag body", () => {
    expect(applyTags("[[note]]**bold** and *act*[[/note]]")).toContain("**bold** and *act*");
  });

  it("leaves unclosed, mismatched and unknown tags literal", () => {
    for (const s of ["[[key]]open", "[[key]]x[[/note]]", "[[foo]]x[[/foo]]"]) {
      expect(applyTags(s)).toBe(s);
    }
  });

  it("does not touch tags inside code fences or inline code", () => {
    const fenced = "```\n[[key]]x[[/key]]\n```";
    expect(applyTags(fenced)).toBe(fenced);
    const unclosedFence = "~~~md\n[[key]]x[[/key]]";
    expect(applyTags(unclosedFence)).toBe(unclosedFence);
    expect(applyTags("`[[key]]x[[/key]]`")).toBe("`[[key]]x[[/key]]`");
  });

  it("still converts tags outside a fence in the same text", () => {
    expect(applyTags("```\n[[key]]a[[/key]]\n```\n[[key]]b[[/key]]")).toBe(
      '```\n[[key]]a[[/key]]\n```\n<mark class="hl-key">b</mark>',
    );
  });
});

describe("applyTags while streaming", () => {
  it("closes an open tag so the highlight appears immediately", () => {
    expect(applyTags("a [[key]]b", true)).toBe('a <mark class="hl-key">b</mark>');
  });

  it("hides a marker that is still arriving", () => {
    for (const tail of ["[", "[[", "[[ke", "[[/key]", "[[/ke"]) {
      expect(applyTags(`hello [[key]]x${tail}`, true)).toBe('hello <mark class="hl-key">x</mark>');
    }
  });

  it("leaves closed tags and code alone", () => {
    expect(applyTags("[[key]]x[[/key]]", true)).toBe('<mark class="hl-key">x</mark>');
    const fenced = "```\n[[key]]x";
    expect(applyTags(fenced, true)).toBe(fenced);
  });
});

