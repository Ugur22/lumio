import { describe, expect, it } from "vitest";
import { buildFixPrompt, canFix, MAX_FIX_OUTPUT } from "./fixPrompt";
import { buildStdin } from "./replay";
import { reduceRun, startState, type RunAction } from "./state";

const run = (runtime: "python" | "javascript", ...actions: RunAction[]) => actions.reduce(reduceRun, startState(runtime));
const eof = { type: "stderr", text: "EOFError: EOF when reading a line\n" } as const;
const failed = run("python", { type: "stderr", text: "ValueError: bad\n" }, { type: "done", ok: false, elapsedMs: 5 });

describe("canFix", () => {
  it("is true for a real error and for a timeout", () => {
    expect(canFix(failed)).toBe(true);
    expect(canFix(run("javascript", { type: "timeout", phase: "running", limitMs: 10_000 }))).toBe(true);
  });

  it("is false for success, running, stopped and idle-like states", () => {
    expect(canFix(run("javascript", { type: "done", ok: true, elapsedMs: 1 }))).toBe(false);
    expect(canFix(startState("javascript"))).toBe(false);
    expect(canFix(run("javascript", { type: "stopped" }))).toBe(false);
  });

  it("is false when the program is only waiting for input, with or without answers", () => {
    const done = { type: "done", ok: false, elapsedMs: 1 } as const;
    expect(canFix(run("python", { type: "echo", text: "1\n" }, eof, done))).toBe(false);
    expect(canFix(run("python", eof, done))).toBe(false);
  });
});

describe("buildFixPrompt", () => {
  it("words an error and refers to the block without including code", () => {
    const text = buildFixPrompt(failed, "python", "");
    expect(text).toContain("This code failed when I ran it. Please fix it and show the corrected full code.");
    expect(text).toContain("Python code block above");
    expect(text).toContain("```\nValueError: bad\n```");
  });

  it("words a timeout with the limit", () => {
    const state = run("javascript", { type: "stdout", text: "tick\n" }, { type: "timeout", phase: "running", limitMs: 10_000 });
    const text = buildFixPrompt(state, "javascript", "");
    expect(text).toContain("didn't finish within 10 seconds");
    expect(text).toContain("JavaScript code block above");
  });

  it("omits stdin when empty and includes it otherwise", () => {
    expect(buildFixPrompt(failed, "python", "  \n")).not.toContain("stdin");
    const text = buildFixPrompt(failed, "python", "1\n2\n");
    expect(text).toContain("stdin I used:\n```\n1\n2\n```");
  });

  it("keeps stdout and stderr in order", () => {
    const state = run("python", { type: "stdout", text: "a\n" }, { type: "stderr", text: "b\n" }, { type: "done", ok: false, elapsedMs: 1 });
    expect(buildFixPrompt(state, "python", "")).toContain("```\na\nb\n```");
  });

  it("keeps the last characters and marks the cut", () => {
    const state = run("python", { type: "stdout", text: "x".repeat(MAX_FIX_OUTPUT) + "TAIL" }, { type: "done", ok: false, elapsedMs: 1 });
    const text = buildFixPrompt(state, "python", "");
    expect(text).toContain("[truncated]");
    expect(text).toContain("xTAIL\n```");
    expect(text).not.toContain("x".repeat(MAX_FIX_OUTPUT + 1));
  });

  it("does not mark short output as truncated", () => {
    expect(buildFixPrompt(failed, "python", "")).not.toContain("[truncated]");
  });

  it("uses a fence longer than any backtick run in the content", () => {
    const state = run("python", { type: "stderr", text: "bad ```` here\n" }, { type: "done", ok: false, elapsedMs: 1 });
    const text = buildFixPrompt(state, "python", "``` x");
    expect(text).toContain("`````\nbad ```` here\n`````");
    expect(text).toContain("````\n``` x\n````");
  });
});

describe("buildFixPrompt with typed answers", () => {
  it("lists the typed answers as the stdin used", () => {
    const text = buildFixPrompt(failed, "python", buildStdin(["10", "+", "abc"]));
    expect(text).toContain("stdin I used:\n```\n10\n+\nabc\n```");
  });
});
