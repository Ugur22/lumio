import { describe, expect, it } from "vitest";
import type { Chat, LoreEntry } from "../types";
import {
  behaviorProblems,
  blankDraft,
  isBehaviorDirty,
  isStoryDirty,
  loreProblems,
  newLoreId,
  parseKeys,
  sanitizeNumber,
  stepNumber,
  storyErrorText,
  toBehaviorBody,
  toBehaviorDraft,
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

describe("behavior drafts", () => {
  const saved = { system_prompt: "Noir.", temperature: 0, top_p: null, frequency_penalty: -1.5, max_tokens: 4000 };

  it("round-trips saved values, keeping 0 and nulls distinct", () => {
    const draft = toBehaviorDraft(saved);

    expect(draft).toEqual({ systemPrompt: "Noir.", temperature: "0", topP: "", frequencyPenalty: "-1.5", maxTokens: "4000" });
    expect(toBehaviorBody(draft)).toEqual(saved);
    expect(isBehaviorDirty(saved, draft)).toBe(false);
  });

  it("treats blank as unset and flags out-of-range or non-integer values", () => {
    const base = toBehaviorDraft(saved);

    expect(behaviorProblems({ ...base, temperature: "" })).toEqual({});
    expect(toBehaviorBody({ ...base, temperature: "" }).temperature).toBeNull();
    expect(Object.keys(behaviorProblems({ ...base, temperature: "2.5", topP: "abc", maxTokens: "1.5" }))).toEqual([
      "temperature",
      "topP",
      "maxTokens",
    ]);
  });

  it("ignores formatting-only differences from the saved numbers", () => {
    const draft = { ...toBehaviorDraft({ ...saved, temperature: 0.85 }), temperature: ".850" };

    expect(isBehaviorDirty({ ...saved, temperature: 0.85 }, draft)).toBe(false);
  });

  it("notices edits", () => {
    expect(isBehaviorDirty(saved, { ...toBehaviorDraft(saved), temperature: "0.7" })).toBe(true);
  });
});

describe("sanitizeNumber", () => {
  it("strips letters and symbols", () => {
    expect(sanitizeNumber("0ghgj", "frequencyPenalty")).toBe("0");
    expect(sanitizeNumber("1e5!", "temperature")).toBe("15");
  });

  it("allows a minus only first, and only where the range goes below zero", () => {
    expect(sanitizeNumber("-1.5", "frequencyPenalty")).toBe("-1.5");
    expect(sanitizeNumber("1-5", "frequencyPenalty")).toBe("15");
    expect(sanitizeNumber("-0.5", "temperature")).toBe("0.5");
  });

  it("keeps one decimal point, reads a comma as the point, and allows none for whole numbers", () => {
    expect(sanitizeNumber("0,85", "temperature")).toBe("0.85");
    expect(sanitizeNumber("1.2.3", "topP")).toBe("1.23");
    expect(sanitizeNumber(".85", "temperature")).toBe(".85");
    expect(sanitizeNumber("4096.5", "maxTokens")).toBe("40965");
  });
});

describe("stepNumber", () => {
  it("steps by the field's increment and avoids float noise", () => {
    expect(stepNumber("0.85", "temperature", 1)).toBe("0.9");
    expect(stepNumber("0.2", "frequencyPenalty", 1)).toBe("0.3");
    expect(stepNumber("4096", "maxTokens", -1)).toBe("3996");
  });

  it("takes ten steps with Shift", () => {
    expect(stepNumber("0.5", "temperature", 1, true)).toBe("1");
  });

  it("clamps to the range and crosses zero only where negatives are allowed", () => {
    expect(stepNumber("2", "temperature", 1)).toBe("2");
    expect(stepNumber("0", "temperature", -1)).toBe("0");
    expect(stepNumber("0", "frequencyPenalty", -1)).toBe("-0.1");
    expect(stepNumber("1", "maxTokens", -1, true)).toBe("1");
  });

  it("starts from zero when the field is blank or unreadable", () => {
    expect(stepNumber("", "topP", 1)).toBe("0.05");
    expect(stepNumber("-", "frequencyPenalty", 1)).toBe("0.1");
  });
});
