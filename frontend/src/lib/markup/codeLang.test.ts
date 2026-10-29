import type { Element, Root } from "hast";
import { describe, expect, it } from "vitest";
import { rehypeExplicitLanguage } from "./codeLang";

const code = (className?: string[]): Element => ({
  type: "element",
  tagName: "code",
  properties: className ? { className } : {},
  children: [{ type: "text", value: "x" }],
});
const tree = (c: Element): Root => ({
  type: "root",
  children: [{ type: "element", tagName: "pre", properties: {}, children: [c] }],
});
const run = (t: Root) => rehypeExplicitLanguage()(t);

describe("rehypeExplicitLanguage", () => {
  it("records the language written on the fence", () => {
    const c = code(["language-python"]);
    run(tree(c));
    expect(c.properties.dataLang).toBe("python");
  });

  it("leaves unlabelled blocks unmarked", () => {
    const c = code();
    run(tree(c));
    expect(c.properties.dataLang).toBeUndefined();
  });

  it("ignores code that is not inside a pre", () => {
    const c = code(["language-js"]);
    run({ type: "root", children: [{ type: "element", tagName: "p", properties: {}, children: [c] }] });
    expect(c.properties.dataLang).toBeUndefined();
  });
});
