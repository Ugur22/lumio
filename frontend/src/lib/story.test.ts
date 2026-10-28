import { describe, expect, it } from "vitest";
import type { Chat, LoreEntry } from "../types";
import {
  blankDraft,
  isStoryDirty,
  loreProblems,
  newLoreId,
  parseKeys,
  storyErrorText,
  toBody,
  toDraft,
  type LoreDraft,
} from "./story";

const chat: Pick<Chat, "bible" | "lore"> = {
  bible: "Moonlit city.",
  lore: [{ id: "a".repeat(32), name: "Mira", keys: ["Mira", "the thief"], content: "Quick hands.", enabled: true }],
};

const entry = chat.lore[0] as LoreEntry;

describe("newLoreId", () => {
  it("makes 32 lowercase hex characters, unique per call", () => {
    const id = newLoreId();
    expect(id).toMatch(/^[0-9a-f]{32}$/);
    expect(newLoreId()).not.toBe(id);
  });
});

describe("parseKeys", () => {
  it("splits on commas, trims, drops blanks and case-insensitive duplicates", () => {
    expect(parseKeys(" Mira, the thief ,, mira,")).toEqual(["Mira", "the thief"]);
    expect(parseKeys("")).toEqual([]);
  });
});

describe("isStoryDirty", () => {
  const drafts = [toDraft(entry)];
  const first = drafts[0] as LoreDraft;

  it("is clean when nothing changed, even if key spacing differs", () => {
    expect(isStoryDirty(chat, chat.bible, drafts)).toBe(false);
    expect(isStoryDirty(chat, chat.bible, [{ ...first, keysText: "Mira,the thief," }])).toBe(false);
  });

  it("notices bible, lore and toggle edits and added entries", () => {
    expect(isStoryDirty(chat, "Other.", drafts)).toBe(true);
    expect(isStoryDirty(chat, chat.bible, [{ ...first, content: "x" }])).toBe(true);
    expect(isStoryDirty(chat, chat.bible, [{ ...first, enabled: false }])).toBe(true);
    expect(isStoryDirty(chat, chat.bible, [...drafts, blankDraft()])).toBe(true);
  });
});

describe("toBody", () => {
  it("turns drafts into the PUT body", () => {
    const d = { ...toDraft(entry), name: "  Mira ", keysText: "a, b" };
    expect(toBody("B", [d]).lore[0]).toEqual({ ...entry, name: "Mira", keys: ["a", "b"] });
  });
});

describe("loreProblems", () => {
  it("flags blank names and over-long fields per entry", () => {
    const ok = toDraft(entry);
    const blank = blankDraft();
    const long = { ...ok, id: "b".repeat(32), content: "x".repeat(5001) };
    const keys = { ...ok, id: "c".repeat(32), keysText: Array.from({ length: 21 }, (_, i) => `k${i}`).join(",") };
    const problems = loreProblems([ok, blank, long, keys]);
    expect(problems.has(ok.id)).toBe(false);
    expect(problems.get(blank.id)).toMatch(/name/);
    expect(problems.get(long.id)).toMatch(/5000/);
    expect(problems.get(keys.id)).toMatch(/20/);
  });
});

describe("storyErrorText", () => {
  it("words 409, 502 and 422 for the action that failed", () => {
    expect(storyErrorText("summarize", 409, "Conflict")).toMatch(/Nothing new/);
    expect(storyErrorText("summarize", 502, "rate limited")).toContain("rate limited");
    expect(storyErrorText("save-summary", 422, "x")).toMatch(/can't be saved/);
    expect(storyErrorText("save-story", 500, "boom")).toBe("boom");
  });
});
