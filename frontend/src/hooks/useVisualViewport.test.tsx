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

  // Frames run only when the test says so.
  function manualFrames() {
    const queue = new Map<number, FrameRequestCallback>();
    let id = 0;
    const request = vi.fn((cb: FrameRequestCallback) => {
      queue.set(++id, cb);
      return id;
    });
    vi.stubGlobal("requestAnimationFrame", request);
    vi.stubGlobal("cancelAnimationFrame", (n: number) => queue.delete(n));
    return {
      request,
      flush: () => {
        const cbs = [...queue.values()];
        queue.clear();
        act(() => cbs.forEach((cb) => cb(0)));
      },
    };
  }

  it("publishes --kb-inset on the next frame and clears it on unmount", () => {
    const frames = manualFrames();
    const vv = Object.assign(new EventTarget(), { height: 800, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", vv);
    vi.stubGlobal("innerHeight", 800);
    const { result, unmount } = renderHook(() => useVisualViewport());
    expect(result.current).toBe(0);
    // Without a keyboard the root keeps its full-screen size.
    expect(document.documentElement.style.getPropertyValue("--vv-height")).toBe("");

    vv.height = 480;
    vv.dispatchEvent(new Event("resize"));
    expect(result.current).toBe(0);
    frames.flush();
    expect(result.current).toBe(320);
    expect(document.documentElement.style.getPropertyValue("--kb-inset")).toBe("320px");
    expect(document.documentElement.dataset.keyboard).toBe("open");

    vv.offsetTop = 40;
    vv.dispatchEvent(new Event("scroll"));
    frames.flush();
    expect(document.documentElement.style.getPropertyValue("--vv-height")).toBe("480px");
    expect(document.documentElement.style.getPropertyValue("--vv-top")).toBe("40px");

    unmount();
    expect(document.documentElement.style.getPropertyValue("--kb-inset")).toBe("");
    expect(document.documentElement.style.getPropertyValue("--vv-top")).toBe("");
    expect(document.documentElement.dataset.keyboard).toBeUndefined();
  });

  it("batches a burst of events into one frame and skips unchanged values", () => {
    const frames = manualFrames();
    const vv = Object.assign(new EventTarget(), { height: 800, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", vv);
    vi.stubGlobal("innerHeight", 800);
    renderHook(() => useVisualViewport());
    const set = vi.spyOn(document.documentElement.style, "setProperty");

    vv.height = 480;
    vv.dispatchEvent(new Event("resize"));
    vv.dispatchEvent(new Event("scroll"));
    vv.dispatchEvent(new Event("resize"));
    expect(frames.request).toHaveBeenCalledTimes(1);
    frames.flush();
    // --kb-inset, --vv-height and --vv-top, once for the whole burst.
    expect(set).toHaveBeenCalledTimes(3);

    vv.dispatchEvent(new Event("scroll"));
    frames.flush();
    expect(set).toHaveBeenCalledTimes(3);
  });

  it("drops the keyboard pin when the keyboard closes without a visualViewport event", () => {
    const frames = manualFrames();
    const vv = Object.assign(new EventTarget(), { height: 800, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", vv);
    vi.stubGlobal("innerHeight", 800);
    renderHook(() => useVisualViewport());
    vv.height = 480;
    vv.dispatchEvent(new Event("resize"));
    frames.flush();
    expect(document.documentElement.style.getPropertyValue("--vv-height")).toBe("480px");

    vv.height = 800;
    window.dispatchEvent(new Event("resize"));
    frames.flush();
    expect(document.documentElement.style.getPropertyValue("--vv-height")).toBe("");
    expect(document.documentElement.dataset.keyboard).toBeUndefined();
  });

  it("re-checks shortly after a field loses focus", () => {
    vi.useFakeTimers();
    try {
      const frames = manualFrames();
      const vv = Object.assign(new EventTarget(), { height: 480, offsetTop: 0, scale: 1 });
      vi.stubGlobal("visualViewport", vv);
      vi.stubGlobal("innerHeight", 800);
      renderHook(() => useVisualViewport());
      frames.flush();
      expect(document.documentElement.dataset.keyboard).toBe("open");

      document.dispatchEvent(new Event("focusout"));
      frames.flush();
      vv.height = 800;
      vi.advanceTimersByTime(400);
      frames.flush();
      expect(document.documentElement.dataset.keyboard).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does nothing without a visualViewport", () => {
    vi.stubGlobal("visualViewport", null);
    const { result } = renderHook(() => useVisualViewport());
    expect(result.current).toBe(0);
  });
});
