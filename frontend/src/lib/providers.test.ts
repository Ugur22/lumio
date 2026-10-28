import { describe, expect, it } from "vitest";
import { detectPreset, hostOf } from "./providers";

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
