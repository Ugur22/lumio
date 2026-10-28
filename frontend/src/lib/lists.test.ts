import { describe, expect, it } from "vitest";
import { continueList, shiftList } from "./lists";

describe("continueList", () => {
  it("continues a dash list", () => {
    expect(continueList("- one", 5)).toEqual({ value: "- one\n- ", caret: 8 });
  });

  it("increments numbered lists and keeps indentation", () => {
    expect(continueList("  2. two", 8)).toEqual({ value: "  2. two\n  3. ", caret: 14 });
  });

  it("splits the line at the caret", () => {
    expect(continueList("- ab", 3)).toEqual({ value: "- a\n- b", caret: 6 });
  });

  it("ends the list on an empty item", () => {
    expect(continueList("- one\n- ", 8)).toEqual({ value: "- one\n", caret: 6 });
  });

  it("ignores plain lines and carets inside the marker", () => {
    expect(continueList("hello", 5)).toBeNull();
    expect(continueList("-dash", 5)).toBeNull();
    expect(continueList("- one", 1)).toBeNull();
  });
});

describe("shiftList", () => {
  it("indents and outdents list items", () => {
    expect(shiftList("- a", 3, false)).toEqual({ value: "  - a", caret: 5 });
    expect(shiftList("  - a", 5, true)).toEqual({ value: "- a", caret: 3 });
  });

  it("leaves plain lines and unindented items alone", () => {
    expect(shiftList("text", 4, false)).toBeNull();
    expect(shiftList("- a", 3, true)).toBeNull();
  });
});
