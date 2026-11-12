// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stubMatchMedia } from "../test/helpers";
import { Turn } from "./Turn";
import { ThinkingStatus, ThinkingView } from "./ThinkingStatus";

beforeEach(() => {
  stubMatchMedia();
  // jsdom has no canvas; the orb skips drawing when there is no context.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const view = (elapsedMs: number, over: Partial<Parameters<typeof ThinkingView>[0]> = {}) =>
  render(<ThinkingView elapsedMs={elapsedMs} reasoning="" query={null} sources={[]} {...over} />);

const counter = (c: HTMLElement) => c.querySelector('[role="status"] [aria-hidden="true"]:last-child');
const label = (c: HTMLElement) => c.querySelector('[role="status"] > span:nth-child(2)');

describe("ThinkingView", () => {
  it("shows the waiting label with no counter for the first 3 seconds", () => {
    const { container } = view(2999);
    expect(label(container)?.textContent).toBe("Thinking");
    expect(counter(container)?.textContent).toBe("");
  });

  it("counts from 3 seconds on and says it is still thinking after 6", () => {
    const { container, rerender } = view(4200);
    expect(counter(container)?.textContent).toBe("· 4s");
    expect(label(container)?.textContent).toBe("Thinking");
    rerender(<ThinkingView elapsedMs={6100} reasoning="" query={null} sources={[]} />);
    expect(label(container)?.textContent).toBe("Still thinking");
    expect(counter(container)?.textContent).toBe("· 6s");
  });

  it("is a status region where only the counter is hidden from assistive tech", () => {
    const { container } = view(5000);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(counter(container)?.getAttribute("aria-hidden")).toBe("true");
    expect(label(container)?.getAttribute("aria-hidden")).toBeNull();
  });

  it("keeps the chips and the reasoning out of the live region", () => {
    const { container } = view(1000, { reasoning: "Hmm" });
    const status = container.querySelector('[role="status"]');
    expect(status?.contains(screen.getByTestId("live-thought"))).toBe(false);
  });

  it("shows the live reasoning panel once reasoning arrives", () => {
    const { container } = view(1000, { reasoning: "The user wants a scene." });
    expect(label(container)?.textContent).toBe("Thinking");
    expect(screen.getByTestId("live-thought").textContent).toBe("The user wants a scene.");
  });

  it("renders reasoning as text, never as HTML or Markdown", () => {
    const evil = '<img src=x onerror="alert(1)"> **bold** <script>alert(2)</script>';
    const { container } = view(1000, { reasoning: evil });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("strong")).toBeNull();
    expect(screen.getByTestId("live-thought").textContent).toBe(evil);
  });

  it("scrolls the live panel to the bottom as reasoning grows", () => {
    const { rerender } = view(1000, { reasoning: "one" });
    const panel = screen.getByTestId("live-thought");
    Object.defineProperty(panel, "scrollHeight", { configurable: true, value: 480 });
    rerender(<ThinkingView elapsedMs={1200} reasoning={"one\ntwo"} query={null} sources={[]} />);
    expect(panel.scrollTop).toBe(480);
  });

  it("names the search with the query as a chip", () => {
    const { container } = view(2000, { query: "Maeslantkering closing criteria" });
    expect(label(container)?.textContent).toBe("Searching the web");
    expect(screen.getByText("Maeslantkering closing criteria")).toBeTruthy();
    expect(screen.queryByTestId("live-thought")).toBeNull();
  });

  it("reads sources with a chip per domain", () => {
    const { container } = view(2000, {
      query: "q",
      sources: [
        { url: "https://www.knmi.nl/a", title: "A" },
        { url: "https://deltawerken.com/b", title: "B" },
      ],
    });
    expect(label(container)?.textContent).toBe("Reading sources");
    expect(screen.getByText("knmi.nl")).toBeTruthy();
    expect(screen.getByText("deltawerken.com")).toBeTruthy();
    expect(screen.queryByText("q")).toBeNull();
  });

  it("keeps the orb out of the accessibility tree so only the label is announced", () => {
    const { container } = view(1000);
    const orb = container.querySelector('[role="status"] > span:first-child');
    expect(orb?.getAttribute("aria-hidden")).toBe("true");
    expect(orb?.querySelector('[role="img"]')).toBeTruthy();
  });

  it("puts a 64px orb in an avatar gutter from 721px up, and a 20px one inline on phones", () => {
    const media = (matches: boolean) =>
      vi.stubGlobal("matchMedia", (q: string) => ({ matches, media: q, addEventListener() {}, removeEventListener() {} }));
    media(true);
    const wide = view(1000, { query: "q" });
    expect(wide.container.querySelector<HTMLCanvasElement>("canvas")?.style.width).toBe("64px");
    expect(wide.container.querySelector('[role="status"] canvas')).toBeNull();
    cleanup();
    media(false);
    const narrow = view(1000);
    expect(narrow.container.querySelector<HTMLCanvasElement>('[role="status"] canvas')?.style.width).toBe("20px");
    vi.unstubAllGlobals();
  });

  it("respects reduced motion by gating every animation on motion-safe", () => {
    const { container } = view(1000);
    const animated = [...container.querySelectorAll("*")].filter((el) => /animate-/.test(el.className.toString()));
    expect(animated.length).toBeGreaterThan(0);
    for (const el of animated) {
      for (const cls of el.className.toString().split(/\s+/).filter((c) => c.includes("animate-"))) {
        expect(cls.startsWith("motion-safe:")).toBe(true);
      }
    }
  });
});

describe("ThinkingStatus clock", () => {
  beforeEach(() => vi.useFakeTimers());

  it("ticks the counter and changes the label only when the phase changes", () => {
    vi.setSystemTime(100_000);
    const { container } = render(<ThinkingStatus startedAt={Date.now()} reasoning="" query={null} sources={[]} />);
    expect(counter(container)?.textContent).toBe("");
    act(() => void vi.advanceTimersByTime(3500));
    expect(counter(container)?.textContent).toBe("· 3s");
    expect(label(container)?.textContent).toBe("Thinking");
    act(() => void vi.advanceTimersByTime(1000));
    expect(counter(container)?.textContent).toBe("· 4s");
    act(() => void vi.advanceTimersByTime(2000));
    expect(label(container)?.textContent).toBe("Still thinking");
  });

  it("stops ticking when it goes away", () => {
    const { unmount } = render(<ThinkingStatus startedAt={Date.now()} reasoning="" query={null} sources={[]} />);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("Turn thinking and thought", () => {
  it("shows the status instead of dots while waiting, and not the old source chips", () => {
    vi.useFakeTimers();
    vi.setSystemTime(50_000);
    const { container } = render(
      <Turn
        question="q"
        reply={{ kind: "thinking", startedAt: 50_000 - 7000, reasoning: "" }}
        query="rust"
        sources={[{ url: "https://knmi.nl/a", title: "A" }]}
      />,
    );
    expect(label(container)?.textContent).toBe("Reading sources");
    expect(container.textContent).not.toContain("Searched:");
    expect(container.textContent).not.toContain("Read 1 source");
    expect(container.querySelector('[aria-label="Thinking"]')).toBeNull();
  });

  const text = { kind: "text", content: "Hello there.", streaming: false } as const;

  it("folds the reasoning into a collapsed toggle that opens and closes", () => {
    render(<Turn question="q" reply={{ ...text, thought: { text: "First this.\nThen that.", seconds: 12 } }} />);
    const toggle = screen.getByRole("button", { name: /Thought for 12s/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();
    expect(panel?.hidden).toBe(true);
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel?.hidden).toBe(false);
    expect(panel?.textContent).toBe("First this.\nThen that.");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("renders the folded reasoning as text, not HTML", () => {
    const evil = '<img src=x onerror="alert(1)"><b>bold</b>';
    const { container } = render(<Turn question="q" reply={{ ...text, thought: { text: evil, seconds: 3 } }} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.innerHTML).not.toContain("<img");
    expect(container.innerHTML).toContain("&lt;img src=x onerror=");
  });

  it("shows no toggle when no reasoning was seen", () => {
    for (const thought of [undefined, null]) {
      const { container, unmount } = render(<Turn question="q" reply={{ ...text, thought }} />);
      expect(container.textContent).not.toContain("Thought for");
      expect(container.querySelector("[aria-expanded]")).toBeNull();
      unmount();
    }
  });

  it("keeps the Read N sources line when text starts", () => {
    const { container } = render(
      <Turn question="q" reply={text} sources={[{ url: "https://knmi.nl/a", title: "A" }]} query="rust" />,
    );
    expect(container.textContent).toContain("Read 1 source");
  });
});

describe("streaming caret", () => {
  it("marks the live reply while it streams and drops the mark when it is done", () => {
    const live = render(<Turn question="q" reply={{ kind: "text", content: "Hello", streaming: true }} />);
    expect(live.container.querySelector("[data-caret]")).not.toBeNull();
    live.unmount();
    const done = render(<Turn question="q" reply={{ kind: "text", content: "Hello" }} />);
    expect(done.container.querySelector("[data-caret]")).toBeNull();
  });

  it("adds no element to the reply, so the rendered Markdown and its sanitizing are untouched", () => {
    const body = "He said **no**.\n\n[[key]]hot[[/key]]";
    const live = render(<Turn question="q" reply={{ kind: "text", content: body, streaming: true }} />);
    const liveHtml = live.container.querySelector("[data-caret]")?.innerHTML;
    live.unmount();
    const done = render(<Turn question="q" reply={{ kind: "text", content: body }} />);
    expect(liveHtml).toBe(done.container.querySelector(".prose")?.innerHTML);
  });

  it("is not carried by a reply that failed", () => {
    const { container } = render(<Turn question="q" reply={{ kind: "error", message: "boom" }} />);
    expect(container.querySelector("[data-caret]")).toBeNull();
  });
});
