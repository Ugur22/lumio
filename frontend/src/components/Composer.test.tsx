// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stubResizeObserver } from "../test/helpers";
import { createRef } from "react";
import { Composer, type ComposerHandle } from "./Composer";

function stubViewport(phone: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: phone && query === "(max-width: 720px)",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

beforeEach(() => {
  stubViewport(false);
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ui = (vision: boolean, canIllustrate?: boolean) => (
  <Composer
    disabled={false}
    vision={vision}
    canIllustrate={canIllustrate}
    providerName="Dolphin"
    onSend={() => undefined}
    onStop={() => undefined}
  />
);
const html = (vision: boolean, canIllustrate?: boolean) => render(ui(vision, canIllustrate)).container.innerHTML;

describe("Composer image button", () => {
  it("is usable on a vision provider", () => {
    const out = html(true);
    expect(out).toContain('aria-disabled="false"');
    expect(out).toContain("Paste or drop images");
  });

  it("stays visible but disabled, and says why, on a text-only provider", () => {
    const out = html(false);
    expect(out).toContain('aria-disabled="true"');
    expect(out).toContain("Dolphin can't read images");
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

describe("Composer on a phone", () => {
  beforeEach(() => stubViewport(true));

  it("replaces the tool row with one + button, without tooltips", () => {
    const out = html(true, true);
    expect(screen.getByRole("button", { name: "Add to message" })).toBeTruthy();
    expect(out).not.toContain('role="tooltip"');
    expect(screen.queryByRole("button", { name: "Search the web" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Attach images" })).toBeNull();
  });

  it("uses a 16px textarea so iOS does not zoom on focus", () => {
    html(true);
    expect(screen.getByLabelText("Message").className).toContain("text-[16px]");
  });

  it("opens a sheet with labelled rows, and Illustrate only when available", async () => {
    const { rerender } = render(ui(true, true));
    await userEvent.setup().click(screen.getByRole("button", { name: "Add to message" }));
    const sheet = await screen.findByRole("dialog", { name: "Add to message" });
    expect(within(sheet).getByRole("button", { name: /Attach images/ })).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: /Search the web/ }).getAttribute("aria-pressed")).toBe("false");
    expect(within(sheet).getByRole("button", { name: /Illustrate the reply/ })).toBeTruthy();
    rerender(ui(true, false));
    expect(within(sheet).queryByRole("button", { name: /Illustrate the reply/ })).toBeNull();
  });

  it("toggles web from the sheet and shows a chip that removes it", async () => {
    const user = userEvent.setup();
    render(ui(true));
    await user.click(screen.getByRole("button", { name: "Add to message" }));
    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: /Search the web/ }));
    expect(within(sheet).getByRole("button", { name: /Search the web/ }).getAttribute("aria-pressed")).toBe("true");
    await user.keyboard("{Escape}");
    const chip = await screen.findByRole("button", { name: "Turn off web search" });
    expect(chip.textContent).toContain("Web on");
    await user.click(chip);
    expect(screen.queryByRole("button", { name: "Turn off web search" })).toBeNull();
  });

  it("explains why attaching is unavailable and does not open the picker", async () => {
    const user = userEvent.setup();
    render(ui(false));
    await user.click(screen.getByRole("button", { name: "Add to message" }));
    const sheet = await screen.findByRole("dialog");
    const row = within(sheet).getByRole("button", { name: /Attach images/ });
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(sheet.textContent).toContain("Dolphin can't read images");
    await user.click(row);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("explains each sheet row on one line and shows the provider name", async () => {
    const user = userEvent.setup();
    render(ui(true, true));
    await user.click(screen.getByRole("button", { name: "Add to message" }));
    const sheet = await screen.findByRole("dialog");
    expect(sheet.textContent).toContain("Up to 4. Dolphin can read them.");
    expect(sheet.textContent).toContain("Looks it up first, then answers.");
    expect(sheet.textContent).toContain("Adds pictures between paragraphs.");
  });

  it("does not animate the card border or shadow on focus", () => {
    const { container } = render(ui(true));
    expect(container.innerHTML).not.toContain("transition-[border-color,box-shadow]");
  });

  it("exposes enableWeb and openPicker on the handle", async () => {
    const ref = createRef<ComposerHandle>();
    const { rerender } = render(<Composer ref={ref} disabled={false} vision providerName="Dolphin" onSend={() => undefined} onStop={() => undefined} />);
    const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => undefined);
    act(() => ref.current?.openPicker());
    expect(click).toHaveBeenCalledTimes(1);
    act(() => ref.current?.enableWeb());
    expect(await screen.findByRole("button", { name: "Turn off web search" })).toBeTruthy();
    rerender(<Composer ref={ref} disabled={false} vision={false} providerName="Dolphin" onSend={() => undefined} onStop={() => undefined} />);
    act(() => ref.current?.openPicker());
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toContain("Dolphin can't read images");
    click.mockRestore();
  });
});
