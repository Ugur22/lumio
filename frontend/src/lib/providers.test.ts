import { describe, expect, it } from "vitest";
import type { Profile, ProfileList } from "../types";
import { detectPreset, effectiveProfile, hostOf, PRESETS } from "./providers";

describe("detectPreset", () => {
  it.each([
    ["sk-or-v1-abc", "openrouter"],
    ["sk-ant-api03-abc", "anthropic"],
    ["gsk_abc", "groq"],
    ["xai-abc123", "xai"],
    ["sk-proj-abc", "openai"],
    ["sk-abc", "openai"],
  ])("%s -> %s", (key, id) => {
    expect(detectPreset(key)?.id).toBe(id);
  });

  it("returns nothing for keys with no recognisable prefix", () => {
    expect(detectPreset("a1b2c3")).toBeUndefined();
    expect(detectPreset("")).toBeUndefined();
  });

  it("ignores surrounding whitespace", () => {
    expect(detectPreset("  gsk_abc ")?.id).toBe("groq");
  });
});

describe("hostOf", () => {
  it("shows host and port, and tolerates junk", () => {
    expect(hostOf("http://localhost:11434/v1")).toBe("localhost:11434");
    expect(hostOf("not a url")).toBe("not a url");
  });
});

describe("vision defaults", () => {
  it("turns image input on for Grok and off for text-only defaults", () => {
    const vision = Object.fromEntries(PRESETS.map((p) => [p.id, p.vision]));
    expect(vision.xai).toBe(true);
    expect(vision.dolphin).toBe(false);
    expect(vision.ollama).toBe(false);
    expect(vision.custom).toBe(false);
  });
});

describe("image model defaults", () => {
  it("prefills only the xAI preset", () => {
    const models = Object.fromEntries(PRESETS.map((p) => [p.id, p.imageModel]));
    expect(models.xai).toBe("grok-imagine-image-2.0");
    expect(models.openai).toBeUndefined();
    expect(models.custom).toBeUndefined();
  });
});

describe("DeepSeek preset", () => {
  it("points at the DeepSeek API and leaves sk- keys to the OpenAI hint", () => {
    const p = PRESETS.find((x) => x.id === "deepseek");
    expect(p?.baseUrl).toBe("https://api.deepseek.com/v1");
    expect(p?.model).toBe("deepseek-chat");
    expect(detectPreset("sk-abc123")?.id).toBe("openai");
  });
});

describe("effectiveProfile", () => {
  const p = (id: string) => ({ id }) as Profile;
  const list: ProfileList = { active: "a", profiles: [p("a"), p("b")] };

  it("prefers the chat's own provider", () => {
    expect(effectiveProfile(list, "b")).toEqual({ profile: p("b"), fellBack: false });
  });

  it("follows the default when the chat has none", () => {
    expect(effectiveProfile(list, null)).toEqual({ profile: p("a"), fellBack: false });
  });

  it("falls back and flags it when the chat's provider was deleted", () => {
    expect(effectiveProfile(list, "gone")).toEqual({ profile: p("a"), fellBack: true });
  });

  it("does not flag a fallback before profiles load", () => {
    expect(effectiveProfile(undefined, "b")).toEqual({ profile: undefined, fellBack: false });
  });
});
