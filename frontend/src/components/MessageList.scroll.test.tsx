// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useStream } from "../store/stream";
import { MessageList } from "./MessageList";

let notify: () => void = () => undefined;

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(cb: () => void) {
        notify = cb;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
  Element.prototype.scrollTo = () => undefined;
  useStream.getState().start("c1", "next chapter");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useStream.getState().clear();
});

function list() {
  const { container } = render(<MessageList messages={[]} chatId="c1" onManage={() => undefined} />);
  const section = container.querySelector("section")!;
  Object.defineProperty(section, "scrollHeight", { configurable: true, value: 900 });
  Object.defineProperty(section, "clientHeight", { configurable: true, value: 500 });
  return section;
}

it("keeps following the bottom when the content grows while the reader is there", () => {
  const section = list();
  act(() => notify());
  expect(section.scrollTop).toBe(900);
});

it("leaves the reader alone once they scrolled up", () => {
  const section = list();
  section.scrollTop = 100;
  act(() => {
    section.dispatchEvent(new Event("scroll"));
    notify();
  });
  expect(section.scrollTop).toBe(100);
});
