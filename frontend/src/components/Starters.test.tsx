import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Starters } from "./MessageList";

const html = (props: { disabled?: boolean; leavingAt?: number } = {}) =>
  renderToStaticMarkup(<Starters disabled={props.disabled ?? false} leavingAt={props.leavingAt} onPick={() => undefined} onStory={() => undefined} />);

const tile = (out: string, title: string) => out.split("<button").find((chunk) => chunk.includes(title)) ?? "";

describe("Starters", () => {
  it("shows all four tiles", () => {
    const out = html();
    for (const t of ["Open a story", "Continue the scene", "Tighten my writing", "Explain simply"]) expect(out).toContain(t);
  });

  it("disables only the tiles that send while a reply is streaming", () => {
    const out = html({ disabled: true });
    expect(tile(out, "Open a story")).toContain(' disabled=""');
    expect(tile(out, "Tighten my writing")).not.toContain(' disabled=""');
  });

  it("leaves flow and becomes inert while fading out", () => {
    const out = html({ leavingAt: 120 });
    expect(out).toContain("position:absolute");
    expect(out).toContain("top:120px");
    expect(out).toContain("pointer-events-none");
  });
});
