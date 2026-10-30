import type { BehaviorBody, Chat, LoreEntry, StoryBody } from "../types";

export const MAX_BIBLE = 20000;
export const MAX_SUMMARY = 20000;
export const MAX_SYSTEM_PROMPT = 10000;
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

export type StoryAction = "summarize" | "save-summary" | "save-story" | "save-behavior";

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

// Numbers stay strings while typing so "0." and "-" survive; blank means "don't send it".
export interface BehaviorDraft {
  systemPrompt: string;
  temperature: string;
  topP: string;
  frequencyPenalty: string;
  maxTokens: string;
}

export const BEHAVIOR_LIMITS = {
  temperature: { min: 0, max: 2 },
  topP: { min: 0, max: 1 },
  frequencyPenalty: { min: -2, max: 2 },
  maxTokens: { min: 1, max: 1_000_000 },
} as const;

const text = (n: number | null) => (n === null ? "" : String(n));

export function toBehaviorDraft(chat: Pick<Chat, Exclude<keyof BehaviorBody, "profile_id">>): BehaviorDraft {
  return {
    systemPrompt: chat.system_prompt,
    temperature: text(chat.temperature),
    topP: text(chat.top_p),
    frequencyPenalty: text(chat.frequency_penalty),
    maxTokens: text(chat.max_tokens),
  };
}

export type NumericField = keyof typeof BEHAVIOR_LIMITS;

// Drops anything that can't be part of the field's number as it is typed: letters, a minus where the
// range has no negatives, a decimal point on a whole-number field, and repeats of either. A comma counts as the point.
export function sanitizeNumber(value: string, field: NumericField): string {
  const negative = BEHAVIOR_LIMITS[field].min < 0;
  const decimal = field !== "maxTokens";
  let out = "";
  for (const raw of value) {
    const ch = raw === "," ? "." : raw;
    if (ch >= "0" && ch <= "9") out += ch;
    else if (ch === "." && decimal && !out.includes(".")) out += ch;
    else if (ch === "-" && negative && out === "") out += ch;
  }
  return out;
}

// Arrow-key step per field; Shift multiplies it by ten.
const STEPS: Record<NumericField, number> = { temperature: 0.05, topP: 0.05, frequencyPenalty: 0.1, maxTokens: 100 };

// The next value for ArrowUp/ArrowDown, clamped to the field's range. A blank or unreadable field steps from 0.
export function stepNumber(value: string, field: NumericField, direction: 1 | -1, big = false): string {
  const { min, max } = BEHAVIOR_LIMITS[field];
  const current = Number(value);
  const from = value.trim() && Number.isFinite(current) ? current : 0;
  const next = Math.min(max, Math.max(min, from + direction * STEPS[field] * (big ? 10 : 1)));
  // Rounded so 0.1 + 0.2 reads 0.3, not 0.30000000000000004.
  return String(Math.round(next * 100) / 100);
}

// null for a blank field, NaN for text that isn't an acceptable number.
function parseField(value: string, field: NumericField): number | null {
  if (!value.trim()) return null;
  const n = Number(value);
  const { min, max } = BEHAVIOR_LIMITS[field];
  const ok = Number.isFinite(n) && n >= min && n <= max && (field !== "maxTokens" || Number.isInteger(n));
  return ok ? n : NaN;
}

export function behaviorProblems(d: BehaviorDraft): Partial<Record<NumericField, string>> {
  const problems: Partial<Record<NumericField, string>> = {};
  for (const field of Object.keys(BEHAVIOR_LIMITS) as NumericField[]) {
    if (Number.isNaN(parseField(d[field], field))) {
      const { min, max } = BEHAVIOR_LIMITS[field];
      problems[field] = `${field === "maxTokens" ? "A whole number" : "A number"} from ${min.toLocaleString()} to ${max.toLocaleString()}`;
    }
  }
  return problems;
}

// Only meaningful once behaviorProblems(d) is empty.
export function toBehaviorBody(d: BehaviorDraft): BehaviorBody {
  return {
    system_prompt: d.systemPrompt,
    temperature: parseField(d.temperature, "temperature"),
    top_p: parseField(d.topP, "topP"),
    frequency_penalty: parseField(d.frequencyPenalty, "frequencyPenalty"),
    max_tokens: parseField(d.maxTokens, "maxTokens"),
  };
}

// Compared as numbers, so ".85" typed against a saved 0.85 isn't mistaken for an edit.
export function isBehaviorDirty(chat: Pick<Chat, Exclude<keyof BehaviorBody, "profile_id">>, d: BehaviorDraft): boolean {
  if (Object.keys(behaviorProblems(d)).length > 0) return true;
  return JSON.stringify(toBehaviorBody(d)) !== JSON.stringify(toBehaviorBody(toBehaviorDraft(chat)));
}
