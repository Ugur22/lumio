import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markup } from "./Markup";

const html = (text: string) => renderToStaticMarkup(<Markup text={text} />);

describe("Markup", () => {
  it("strips script elements and event handlers from reply text", () => {
    const out = html('hi <script>alert(1)</script> <img src="x" onerror="alert(2)"> <a href="javascript:alert(3)">x</a>');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("javascript:");
  });

  it("renders highlight tags with only the allowed classes", () => {
    const out = html("[[key]]**hot**[[/key]]\n\n[[warn]]careful[[/warn]]");
    expect(out).toContain('<mark class="hl-key"><strong>hot</strong></mark>');
    expect(out).toContain('<aside class="hl-warn">');
  });

  it("keeps safe inline styles on text blocks and strips the rest", () => {
    const out = html(
      '<div style="background:#17212b;color:#fff;position:fixed;background-image:url(https://x.test/a.png)" onclick="x()">hi</div>',
    );
    expect(out).toContain('style="background:#17212b;color:#fff"');
    expect(out).not.toContain("position");
    expect(out).not.toContain("url(");
    expect(out).not.toContain("onclick");
  });

  it("does not allow style on elements outside the styled list", () => {
    expect(html('<table style="color:red"><tr><td>x</td></tr></table>')).not.toContain("style=");
  });

  it("leaves dialogue colouring off inside a model-styled block", () => {
    const out = html('<div style="color:#fff">she said "hi"</div>\n\nthen "bye"');
    expect(out.match(/class="dialogue"/g)).toHaveLength(1);
  });

  it("drops classes outside the allowlist", () => {
    expect(html('<mark class="evil">x</mark>')).not.toContain("evil");
  });

  it("styles dialogue and actions but not code", () => {
    const out = html('She said "hello" *smiles*\n\n```\n"quoted"\n```');
    expect(out).toContain('<span class="dialogue">“hello”</span>');
    expect(out).toContain("<em>smiles</em>");
    expect(out).toContain("&quot;quoted&quot;");
    expect(out.match(/dialogue/g)).toHaveLength(1);
  });

  it("curls apostrophes and dialogue quotes without touching code", () => {
    const out = html("It's late. \"Don't go,\" she said.\n\n`don't`");
    expect(out).toContain("It’s late.");
    expect(out).toContain("“Don’t go,”");
    expect(out).toContain("<code>don&#x27;t</code>");
  });

  it("leaves tags inside a code fence literal", () => {
    const out = html("```\n[[key]]x[[/key]]\n```");
    expect(out).toContain("[[key]]");
    expect(out).not.toContain("<mark");
  });

  it("keeps unclosed tags as text", () => {
    expect(html("[[note]]never closed")).toContain("[[note]]never closed");
  });
});
