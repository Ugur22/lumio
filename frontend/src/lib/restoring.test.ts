import { describe, expect, it } from "vitest";
import { isRestoring } from "./restoring";

const base = { chosen: undefined, listPending: false, currentId: null, chatPending: false };

describe("isRestoring", () => {
  it("waits while the chat list is still loading", () => {
    expect(isRestoring({ ...base, listPending: true })).toBe(true);
  });

  it("waits for the newest chat once the list has loaded", () => {
    expect(isRestoring({ ...base, currentId: "a", chatPending: true })).toBe(true);
  });

  it("is done when the newest chat has loaded", () => {
    expect(isRestoring({ ...base, currentId: "a" })).toBe(false);
  });

  it("shows the blank chat when the list loaded and is empty", () => {
    expect(isRestoring(base)).toBe(false);
  });

  it("ignores a disabled chat query that reports pending", () => {
    expect(isRestoring({ ...base, currentId: null, chatPending: true })).toBe(false);
  });

  it("never waits once the user has chosen, including New chat", () => {
    expect(isRestoring({ ...base, chosen: null, listPending: true })).toBe(false);
    expect(isRestoring({ ...base, chosen: "b", currentId: "b", chatPending: true })).toBe(false);
  });
});
