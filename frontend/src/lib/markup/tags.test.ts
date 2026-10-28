import { describe, expect, it } from "vitest";
import { applyTags } from "./tags";

describe("applyTags", () => {
  it("turns key into mark and note/warn into asides", () => {
    expect(applyTags("a [[key]]b[[/key]]")).toBe('a <mark class="hl-key">b</mark>');
    expect(applyTags("[[note]]n[[/note]]")).toBe('<aside class="hl-note">\n\nn\n\n</aside>');
    expect(applyTags("[[warn]]w[[/warn]]")).toBe('<aside class="hl-warn">\n\nw\n\n</aside>');
  });

  it("keeps markdown inside the tag body", () => {
    expect(applyTags("[[note]]**bold** and *act*[[/note]]")).toContain("**bold** and *act*");
  });

  it("leaves unclosed, mismatched and unknown tags literal", () => {
    for (const s of ["[[key]]open", "[[key]]x[[/note]]", "[[foo]]x[[/foo]]"]) {
      expect(applyTags(s)).toBe(s);
    }
  });

  it("renders a closed html fence holding a styled div instead of showing it as code", () => {
    const fenced = 'Here:\n```html\n<div style="color:red">\n\n  <p>hi</p>\n</div>\n```\nafter';
    expect(applyTags(fenced)).toBe('Here:\n<div style="color:red">\n<p>hi</p>\n</div>\nafter');
  });

  it("keeps an unfenced styled block together across blank lines and deep indentation", () => {
    const raw = 'Intro\n<div style="color:red">\n  <div style="a:b">x</div>\n\n    <div style="c:d">\n      y\n    </div>\n</div>\nAfter text\n\n    real code';
    expect(applyTags(raw)).toBe(
      'Intro\n<div style="color:red">\n<div style="a:b">x</div>\n<div style="c:d">\ny\n</div>\n</div>\nAfter text\n\n    real code',
    );
  });

  it("keeps ordinary html code, and unfinished fences, as code", () => {
    for (const s of ["```html\n<div class=\"a\">x</div>\n```", '```html\n<div style="color:red">x</div>', '```css\n<div style="a">x</div>\n```']) {
      expect(applyTags(s)).toBe(s);
    }
  });

  it("does not touch tags inside code fences or inline code", () => {
    const fenced = "```\n[[key]]x[[/key]]\n```";
    expect(applyTags(fenced)).toBe(fenced);
    const unclosedFence = "~~~md\n[[key]]x[[/key]]";
    expect(applyTags(unclosedFence)).toBe(unclosedFence);
    expect(applyTags("`[[key]]x[[/key]]`")).toBe("`[[key]]x[[/key]]`");
  });

  it("still converts tags outside a fence in the same text", () => {
    expect(applyTags("```\n[[key]]a[[/key]]\n```\n[[key]]b[[/key]]")).toBe(
      '```\n[[key]]a[[/key]]\n```\n<mark class="hl-key">b</mark>',
    );
  });
});

describe("applyTags while streaming", () => {
  it("closes an open tag so the highlight appears immediately", () => {
    expect(applyTags("a [[key]]b", true)).toBe('a <mark class="hl-key">b</mark>');
  });

  it("hides a marker that is still arriving", () => {
    for (const tail of ["[", "[[", "[[ke", "[[/key]", "[[/ke"]) {
      expect(applyTags(`hello [[key]]x${tail}`, true)).toBe('hello <mark class="hl-key">x</mark>');
    }
  });

  it("leaves closed tags and code alone", () => {
    expect(applyTags("[[key]]x[[/key]]", true)).toBe('<mark class="hl-key">x</mark>');
    const fenced = "```\n[[key]]x";
    expect(applyTags(fenced, true)).toBe(fenced);
  });

  describe("stray web_source tokens", () => {
    it("strips [[web_source ...]] tokens, including quoted attribute values", () => {
      const raw =
        'Fact [[web_source url="https://a.com/x?q=[1]" title="He said \'hi\' > ok"]]more[[/web_source]] end';
      expect(applyTags(raw)).toBe("Fact more end");
      expect(applyTags("a [[web_source url='https://a.com' title=\"A ]] title\"]] b")).not.toContain(
        "web_source",
      );
    });

    it("strips <web_source> fragments", () => {
      expect(applyTags('a <web_source url="https://a.com" title="t>x">b</web_source> c')).toBe("a b c");
    });

    it("still renders normal tags next to a stray token", () => {
      expect(applyTags('[[key]]k[[/key]] [[web_source url="u" title="t"]]')).toBe('<mark class="hl-key">k</mark> ');
    });

    it("leaves tokens inside code literal", () => {
      expect(applyTags('`[[web_source url="u"]]`')).toBe('`[[web_source url="u"]]`');
    });

    it("hides a half-typed token while streaming", () => {
      expect(applyTags("text [[web_so", true)).toBe("text ");
      expect(applyTags('text [[web_source url="https://a', true)).toBe("text ");
      expect(applyTags("text [[key]]a", true)).toBe('text <mark class="hl-key">a</mark>');
    });
  });
});
