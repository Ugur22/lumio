import { describe, expect, it } from "vitest";
import { answerFeedback, atCap, buildStdin, diverged, MAX_ANSWERS, outputText } from "./replay";

describe("diverged", () => {
  it("accepts a replay that repeats the earlier output and goes on", () => {
    expect(diverged("Name? ada\n", "Name? ada\nHi ada\n")).toBe(false);
    expect(diverged("Name? ", "Name? ")).toBe(false);
    expect(diverged("", "anything")).toBe(false);
  });

  it("flags output that changed or got shorter", () => {
    expect(diverged("Roll: 4\n", "Roll: 2\nMore\n")).toBe(true);
    expect(diverged("Name? ada\n", "Name? ")).toBe(true);
  });
});

describe("outputText", () => {
  it("joins stdout and echo and leaves stderr out", () => {
    expect(
      outputText([
        { stream: "stdout", text: "A? " },
        { stream: "echo", text: "1\n" },
        { stream: "stderr", text: "EOFError\n" },
      ]),
    ).toBe("A? 1\n");
  });
});

describe("stdin construction", () => {
  it("terminates each line so a final empty answer survives the worker", () => {
    expect(buildStdin(["1", "", "x"])).toBe("1\n\nx\n");
    const worker = (s: string) => (s === "" ? [] : s.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n"));
    expect(worker(buildStdin(["a", ""]))).toEqual(["a", ""]);
    expect(buildStdin([])).toBe("");
  });

  it("feeds typed answers in the order they were given", () => {
    expect(buildStdin(["1", "2", "+", "quit"])).toBe("1\n2\n+\nquit\n");
  });
});

describe("atCap", () => {
  it("stops at the maximum", () => {
    expect(MAX_ANSWERS).toBe(200);
    expect(atCap(199)).toBe(false);
    expect(atCap(200)).toBe(true);
  });
});

describe("answerFeedback", () => {
  const out = (text: string) => ({ stream: "stdout", text });
  const echo = (text: string) => ({ stream: "echo", text });
  const prev = [out("Enter operation...: ")];

  it("is silent when nothing followed the answer", () => {
    expect(answerFeedback(prev, [out("Enter operation...: "), echo("x\n")], ["x"])).toBe("silent");
    expect(answerFeedback(prev, [out("Enter operation...: "), echo("x\n"), out(" \n")], ["x"])).toBe("silent");
  });

  it("notices the same prompt asked again", () => {
    const next = [out("Enter operation...: "), echo("x\n"), out("Enter operation...: ")];
    expect(answerFeedback(prev, next, ["x"])).toBe("repeated");
  });

  it("stays quiet for a different reply", () => {
    const next = [out("Enter operation...: "), echo("+\n"), out("First number: ")];
    expect(answerFeedback(prev, next, ["+"])).toBeNull();
  });

  it("compares the last line of a multi-line prompt", () => {
    const menu = [out("Menu\n1) add\n2) quit\nChoice: ")];
    const next = [...menu, echo("9\n"), out("Menu\n1) add\n2) quit\nChoice: ")];
    expect(answerFeedback(menu, next, ["9"])).toBe("repeated");
    expect(answerFeedback(menu, [...menu, echo("1\n"), out("Menu\n1) add\n2) quit\nNumber: ")], ["1"])).toBeNull();
  });

  it("looks only after the last echo and ignores stderr", () => {
    const next = [out("Q? "), echo("1\n"), out("Q? "), echo("2\n"), { stream: "stderr", text: "EOFError\n" }];
    expect(answerFeedback([out("Q? 1\nQ? ")], next, ["1", "2"])).toBe("silent");
  });

  it("has nothing to say without an answer or an echo", () => {
    expect(answerFeedback(prev, [out("hi")], ["x"])).toBeNull();
    expect(answerFeedback(prev, [echo("x\n")], [])).toBeNull();
  });
});
