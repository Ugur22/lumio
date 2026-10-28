import type { Element, Root } from "hast";
import { describe, expect, it } from "vitest";
import { rehypeDialogue, splitDialogue } from "./dialogue";

describe("splitDialogue", () => {
  it("finds multiple straight and curly quotes on one line", () => {
    expect(splitDialogue('He said "hi" then “bye” and left')).toEqual([
      { text: "He said ", dialogue: false },
      { text: '"hi"', dialogue: true },
      { text: " then ", dialogue: false },
      { text: "“bye”", dialogue: true },
      { text: " and left", dialogue: false },
    ]);
  });

  it("ignores unbalanced quotes", () => {
    expect(splitDialogue('5" pipe')).toEqual([{ text: '5" pipe', dialogue: false }]);
  });
});

describe("rehypeDialogue", () => {
  const el = (tagName: string, ...children: Element["children"]): Element => ({
    type: "element",
    tagName,
    properties: {},
    children,
  });
  const text = (value: string) => ({ type: "text" as const, value });

  it("wraps quotes in paragraphs but skips code and pre", () => {
    const tree: Root = {
      type: "root",
      children: [el("p", text('say "yes"')), el("pre", el("code", text('print("x")'))), el("p", el("code", text('"a"')))],
    };
    rehypeDialogue()(tree);
    const [p, pre, p2] = tree.children as Element[];
    expect((p?.children[1] as Element).properties).toEqual({ className: ["dialogue"] });
    expect(JSON.stringify(pre)).not.toContain("dialogue");
    expect(JSON.stringify(p2)).not.toContain("dialogue");
  });
});
