import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Composer } from "./Composer";

const html = (vision: boolean) =>
  renderToStaticMarkup(
    <Composer disabled={false} vision={vision} providerName="Dolphin" onSend={() => undefined} onStop={() => undefined} />,
  );

describe("Composer image button", () => {
  it("is usable on a vision provider", () => {
    const out = html(true);
    expect(out).toContain('aria-disabled="false"');
    expect(out).toContain("Paste or drop images");
  });

  it("stays visible but disabled, and says why, on a text-only provider", () => {
    const out = html(false);
    expect(out).toContain('aria-disabled="true"');
    expect(out).toContain("Dolphin can&#x27;t read images");
    expect(out).not.toContain("Paste or drop images");
  });
});
