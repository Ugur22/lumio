import { describe, expect, it } from "vitest";
import { modelBody, overrideModel, shownModel, showDefaultItem } from "./chatModel";

const pick = { model: "openai/gpt-5", context_window: 400000 };

describe("shownModel", () => {
  it("shows the chat's override over the profile's model", () => {
    expect(shownModel({ chatModel: "gpt-x", pending: null, profileModel: "base", blank: false })).toBe("gpt-x");
  });

  it("falls back to the profile's model when the chat has no override or is still loading", () => {
    expect(shownModel({ chatModel: null, pending: null, profileModel: "base", blank: false })).toBe("base");
    expect(shownModel({ chatModel: undefined, pending: null, profileModel: "base", blank: false })).toBe("base");
  });

  it("shows the pending pick on a blank chat, else the profile's model", () => {
    expect(shownModel({ chatModel: undefined, pending: pick, profileModel: "base", blank: true })).toBe("openai/gpt-5");
    expect(shownModel({ chatModel: undefined, pending: null, profileModel: "base", blank: true })).toBe("base");
  });

  it("ignores a stale pending pick once a chat is open", () => {
    expect(shownModel({ chatModel: null, pending: pick, profileModel: "base", blank: false })).toBe("base");
  });
});

describe("modelBody", () => {
  it("carries the window the provider listed for the model", () => {
    expect(modelBody("a", { a: 8192 })).toEqual({ model: "a", context_window: 8192 });
  });

  it("sends a null window for a typed or unlisted model", () => {
    expect(modelBody("custom", { a: 8192 })).toEqual({ model: "custom", context_window: null });
  });

  it("drops a window the server would reject", () => {
    expect(modelBody("tiny", { tiny: 512 })).toEqual({ model: "tiny", context_window: null });
  });

  it("clears the override with a null model and window", () => {
    expect(modelBody(null, { a: 8192 })).toEqual({ model: null, context_window: null });
  });
});

describe("showDefaultItem", () => {
  it("appears only while an override is set", () => {
    expect(showDefaultItem(overrideModel("gpt-x", null, false))).toBe(true);
    expect(showDefaultItem(overrideModel(null, null, false))).toBe(false);
    expect(showDefaultItem(overrideModel(undefined, pick, true))).toBe(true);
    expect(showDefaultItem(overrideModel(undefined, null, true))).toBe(false);
  });
});
