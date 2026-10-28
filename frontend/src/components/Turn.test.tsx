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
