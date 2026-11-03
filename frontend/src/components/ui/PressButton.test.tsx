// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PressButton } from "./PressButton";

function stubTouch(touch: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: touch,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe("PressButton", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("presses with a CSS :active scale on touch screens", () => {
    stubTouch(true);
    render(<PressButton>Go</PressButton>);
    expect(screen.getByRole("button", { name: "Go" }).className).toContain("active:scale-[0.97]");
  });

  it("keeps the spring on desktop, with no CSS press class", () => {
    stubTouch(false);
    render(<PressButton>Go</PressButton>);
    expect(screen.getByRole("button", { name: "Go" }).className).not.toContain("active:scale");
  });

  it("works without matchMedia", () => {
    render(<PressButton>Go</PressButton>);
    expect(screen.getByRole("button", { name: "Go" })).toBeTruthy();
  });
});
