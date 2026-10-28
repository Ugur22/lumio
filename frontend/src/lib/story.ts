import type { Chat, LoreEntry, StoryBody } from "../types";

export const MAX_BIBLE = 20000;
export const MAX_SUMMARY = 20000;
export const MAX_LORE = 200;
export const MAX_CONTENT = 5000;
export const MAX_NAME = 80;
export const MAX_KEYS = 20;
export const MAX_KEY = 60;

// Keys stay a raw string while typing so a trailing comma isn't eaten.
export interface LoreDraft {
  id: string;
  name: string;
  keysText: string;
  content: string;
  enabled: boolean;
}

export function newLoreId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function parseKeys(text: string): string[] {
  const seen = new Set<string>();
  const keys: string[] = [];
  for (const raw of text.split(",")) {
    const key = raw.trim();
    if (key && !seen.has(key.toLowerCase())) {
      seen.add(key.toLowerCase());
      keys.push(key);
    }
  }
  return keys;
}

export const toDraft = (e: LoreEntry): LoreDraft => ({
  id: e.id,
  name: e.name,
  keysText: e.keys.join(", "),
  content: e.content,
  enabled: e.enabled,
});

export const blankDraft = (): LoreDraft => ({ id: newLoreId(), name: "", keysText: "", content: "", enabled: true });

export function toBody(bible: string, drafts: LoreDraft[]): StoryBody {
  return {
    bible,
    lore: drafts.map((d) => ({
      id: d.id,
      name: d.name.trim(),
      keys: parseKeys(d.keysText),
      content: d.content,
      enabled: d.enabled,
    })),
  };
}

// Compared through the same normalisation as a save, so whitespace-only key edits aren't "changes".
export function isStoryDirty(chat: Pick<Chat, "bible" | "lore">, bible: string, drafts: LoreDraft[]): boolean {
  const saved = toBody(chat.bible, chat.lore.map(toDraft));
  return JSON.stringify(saved) !== JSON.stringify(toBody(bible, drafts));
}

// One message per draft id; empty when the whole story can be saved.
export function loreProblems(drafts: LoreDraft[]): Map<string, string> {
  const problems = new Map<string, string>();
  for (const d of drafts) {
    const keys = parseKeys(d.keysText);
    if (!d.name.trim()) problems.set(d.id, "Give this entry a name.");
    else if (d.name.trim().length > MAX_NAME) problems.set(d.id, `Names are limited to ${MAX_NAME} characters.`);
    else if (keys.length > MAX_KEYS) problems.set(d.id, `Use at most ${MAX_KEYS} trigger keys.`);
    else if (keys.some((k) => k.length > MAX_KEY)) problems.set(d.id, `Each key is limited to ${MAX_KEY} characters.`);
    else if (d.content.length > MAX_CONTENT) problems.set(d.id, `Content is limited to ${MAX_CONTENT} characters.`);
  }
  return problems;
}

export type StoryAction = "summarize" | "save-summary" | "save-story";

// The server's detail is generic ("Conflict"); say what it means for the action that failed.
export function storyErrorText(action: StoryAction, status: number | undefined, fallback: string): string {
  if (action === "summarize") {
    if (status === 409) return "Nothing new to condense yet, or no provider is set up. Chat a bit more, then try again.";
    if (status === 502) return `The provider couldn't write the summary: ${fallback}`;
  }
  if (action === "save-summary" && status === 422) {
    return "That summary can't be saved: it needs some text, and can't cover more messages than the chat has.";
  }
  if (status === 422) return `Some fields are not valid: ${fallback}`;
  return fallback;
}
