import { describe, expect, it } from "vitest";
import { needsInput } from "./stdin";

const eof = "Traceback (most recent call last):\n  File \"<exec>\", line 1\nEOFError: EOF when reading a line\n";

describe("needsInput", () => {
  it("is true for a failed run that ended on EOFError", () => {
    expect(needsInput({ status: "error", chunks: [{ stream: "stdout", text: "Name? " }, { stream: "stderr", text: eof }] })).toBe(true);
  });

  it("is true for a failed JavaScript run that ended on the worker's marker line", () => {
    const chunks = [{ stream: "stdout", text: "N? " }, { stream: "stderr", text: "Lumio: waiting for input\n" }];
    expect(needsInput({ status: "error", chunks })).toBe(true);
    expect(needsInput({ status: "ok", chunks })).toBe(false);
    expect(needsInput({ status: "error", chunks: [...chunks, { stream: "stderr", text: "Error: later\n" }] })).toBe(false);
  });

  it("is false for other errors, other statuses and stdout lookalikes", () => {
    expect(needsInput({ status: "error", chunks: [{ stream: "stderr", text: "ValueError: nope\n" }] })).toBe(false);
    expect(needsInput({ status: "ok", chunks: [{ stream: "stderr", text: eof }] })).toBe(false);
    expect(needsInput({ status: "error", chunks: [{ stream: "stdout", text: eof }] })).toBe(false);
    expect(needsInput({ status: "error", chunks: [{ stream: "stderr", text: eof + "ValueError: later\n" }] })).toBe(false);
  });
});
