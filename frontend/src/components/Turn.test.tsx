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

describe("Turn copy button", () => {
  it("offers to copy a finished reply", () => {
    const out = renderToStaticMarkup(<Turn question="q" reply={{ kind: "text", content: "hi" }} />);
    expect(out).toContain('aria-label="Copy message"');
  });

  it("hides it while the reply is still streaming", () => {
    const out = renderToStaticMarkup(<Turn question="q" reply={{ kind: "text", content: "hi", streaming: true }} />);
    expect(out).not.toContain("Copy message");
  });
});

describe("Turn illustrations", () => {
  const id = "0123456789abcdef0123456789abcdef";
  const render = (content: string, known = true, streaming = false) =>
    renderToStaticMarkup(
      <Turn
        question="q"
        reply={{
          kind: "text",
          content,
          streaming,
          illustrations: known ? [{ id, url: "/api/chats/c/images/" + id, prompt: "a harbour" }] : [],
        }}
      />,
    );

  it("renders a stored image with its prompt as caption", () => {
    const out = render(`One.\n\n[[img:${id}]]\n\nTwo.`);
    expect(out).toContain(`src="/api/chats/c/images/${id}"`);
    expect(out).toContain("<figcaption");
    expect(out).toContain("a harbour");
    expect(out).not.toContain("[[img:");
  });

  it("renders nothing for an id the message does not own", () => {
    const out = render(`One.\n[[img:${id}]]\nTwo.`, false);
    expect(out).not.toContain("<img");
    expect(out).not.toContain("[[img:");
  });

  it("shows Illustrating while a directive streams and hides the raw text", () => {
    const out = render("One.\n\n[[image: a lighthouse]]", true, true);
    expect(out).toContain("Illustrating");
    expect(out).not.toContain("lighthouse");
  });
});
