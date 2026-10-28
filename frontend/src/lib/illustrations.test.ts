import { describe, expect, it } from "vitest";
import { copyText, splitReply, type Illustration } from "./illustrations";

const ID = "0123456789abcdef0123456789abcdef";
const pic: Illustration = { id: ID, url: "/img/1", prompt: "a harbour at dusk" };

describe("splitReply", () => {
  it("interleaves text and a known image", () => {
    const out = splitReply(`One.\n\n[[img:${ID}]]\n\nTwo.`, [pic], false);
    expect(out.map((s) => s.kind)).toEqual(["text", "image", "text"]);
  });

  it("ignores an id that is not in the message's images", () => {
    const out = splitReply(`One.\n[[img:${ID}]]\nTwo.`, [], false);
    expect(out.every((s) => s.kind === "text")).toBe(true);
    expect(JSON.stringify(out)).not.toContain("img:");
  });

  it("leaves ordinary brackets alone", () => {
    expect(splitReply("see [[note]] and [x]", [], true)).toEqual([{ kind: "text", text: "see [[note]] and [x]" }]);
  });

  it("shows a placeholder for a complete directive while streaming", () => {
    const out = splitReply("Intro.\n\n[[image: a lighthouse]]\n\nMore", [], true);
    expect(out.map((s) => s.kind)).toEqual(["text", "pending", "text"]);
  });

  it("drops a stale directive once streaming is over", () => {
    const out = splitReply("Intro.\n[[image: a lighthouse]]\nMore", [], false);
    expect(out.map((s) => s.kind)).toEqual(["text", "text"]);
  });

  it.each(["[", "[[", "[[ima", "[[image:", "[[image: a light", "[[img:0123"])("hides the partial tail %j while streaming", (tail) => {
    expect(splitReply(`Intro.${tail}`, [], true)).toEqual([{ kind: "text", text: "Intro." }]);
  });

  it("keeps a partial tail visible when not streaming", () => {
    expect(splitReply("Intro.[[ima", [], false)).toEqual([{ kind: "text", text: "Intro.[[ima" }]);
  });
});

describe("copyText", () => {
  it("removes markers and directives", () => {
    expect(copyText(`One.\n\n[[img:${ID}]]\n\nTwo.`)).toBe("One.\n\nTwo.");
  });
});
