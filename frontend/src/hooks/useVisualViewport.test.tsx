// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { keyboardInset, useVisualViewport } from "./useVisualViewport";

describe("keyboardInset", () => {
  it("is the part of the layout viewport the keyboard covers", () => {
    expect(keyboardInset(800, { height: 500, offsetTop: 0, scale: 1 })).toBe(300);
  });

  it("accounts for the visual viewport being panned", () => {
    expect(keyboardInset(800, { height: 450, offsetTop: 50, scale: 1 })).toBe(300);
  });

  it("ignores small differences such as a collapsing URL bar", () => {
    expect(keyboardInset(800, { height: 740, offsetTop: 0, scale: 1 })).toBe(0);
  });

  it("ignores pinch-zoom", () => {
    expect(keyboardInset(800, { height: 400, offsetTop: 0, scale: 2 })).toBe(0);
  });

  it("never goes negative", () => {
    expect(keyboardInset(600, { height: 800, offsetTop: 0, scale: 1 })).toBe(0);
  });
});

describe("useVisualViewport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.style.removeProperty("--kb-inset");
  });

  it("publishes --kb-inset on resize and clears it on unmount", () => {
    const vv = Object.assign(new EventTarget(), { height: 800, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", vv);
    vi.stubGlobal("innerHeight", 800);
    const { result, unmount } = renderHook(() => useVisualViewport());
    expect(result.current).toBe(0);

    act(() => {
      vv.height = 480;
      vv.dispatchEvent(new Event("resize"));
    });
    expect(result.current).toBe(320);
    expect(document.documentElement.style.getPropertyValue("--kb-inset")).toBe("320px");
    expect(document.documentElement.dataset.keyboard).toBe("open");

    act(() => {
      vv.offsetTop = 40;
      vv.dispatchEvent(new Event("scroll"));
    });
    expect(document.documentElement.style.getPropertyValue("--vv-height")).toBe("480px");
    expect(document.documentElement.style.getPropertyValue("--vv-top")).toBe("40px");

    unmount();
    expect(document.documentElement.style.getPropertyValue("--kb-inset")).toBe("");
    expect(document.documentElement.style.getPropertyValue("--vv-top")).toBe("");
    expect(document.documentElement.dataset.keyboard).toBeUndefined();
  });

  it("does nothing without a visualViewport", () => {
    vi.stubGlobal("visualViewport", null);
    const { result } = renderHook(() => useVisualViewport());
    expect(result.current).toBe(0);
  });
});
