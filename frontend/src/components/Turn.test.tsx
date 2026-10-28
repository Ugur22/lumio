import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Turn } from "./Turn";

describe("Turn images", () => {
  it("renders attached images as a button that opens them, not a link out", () => {
    const out = renderToStaticMarkup(
      <Turn question="what is this?" images={["/api/chats/c/images/i"]} reply={{ kind: "none" }} />,
    );
    expect(out).toContain('aria-label="View attached image 1 full size"');
    expect(out).not.toContain("<a ");
  });

  it("shows an image-only message without an empty bubble", () => {
    const out = renderToStaticMarkup(<Turn question="" images={["/x"]} reply={{ kind: "none" }} />);
    expect(out).not.toContain("rounded-[12px_12px_3px_12px]");
  });
});

describe("Turn search query", () => {
  it("shows the query as muted plain text", () => {
    const out = renderToStaticMarkup(
      <Turn question="q" reply={{ kind: "none" }} query={'rust <b>2026</b> release'} />,
    );
    expect(out).toContain("Searched: ");
    expect(out).toContain("rust &lt;b&gt;2026&lt;/b&gt; release");
    expect(out).not.toContain("<b>");
    expect(out).not.toContain("<a ");
  });

  it("shows it alongside sources", () => {
    const out = renderToStaticMarkup(
      <Turn question="q" reply={{ kind: "none" }} sources={[{ url: "https://a.com/x", title: "A" }]} query="rust" />,
    );
    expect(out).toContain("Searched: rust");
    expect(out).toContain("Read 1 source");
  });

  it("omits it when the query is null, absent or blank", () => {
    for (const query of [null, undefined, "", "   "]) {
      const out = renderToStaticMarkup(<Turn question="q" reply={{ kind: "none" }} query={query} />);
      expect(out).not.toContain("Searched");
    }
  });
});
