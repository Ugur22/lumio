import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Composer } from "./Composer";

const html = (vision: boolean, canIllustrate?: boolean) =>
  renderToStaticMarkup(
    <Composer
      disabled={false}
      vision={vision}
      canIllustrate={canIllustrate}
      providerName="Dolphin"
      onSend={() => undefined}
      onStop={() => undefined}
    />,
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

describe("Composer Illustrate toggle", () => {
  it("appears when the provider has an image model", () => {
    const out = html(false, true);
    expect(out).toContain('aria-label="Illustrate the reply"');
    expect(out).toContain('aria-pressed="false"');
  });

  it("is absent otherwise", () => {
    expect(html(true, false)).not.toContain("Illustrate");
    expect(html(true)).not.toContain("Illustrate");
  });
});

describe("Composer toolbar tooltips", () => {
  it("exposes each tooltip text through aria-describedby and drops native titles", () => {
    const out = html(true, true);
    for (const [id, text] of [
      ["web-tip", "Looks your message up online"],
      ["illustrate-tip", "Adds pictures between the paragraphs"],
      ["image-tip", "Choose up to 4 images"],
    ]) {
      expect(out).toContain(`aria-describedby="${id}"`);
      expect(out).toMatch(new RegExp(`id="${id}" role="tooltip"[^>]*>.*${text}`));
    }
    expect(out).not.toContain("title=");
  });
});
