// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { Composer, type ComposerHandle } from "./Composer";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const view = (locked: boolean, onSend = vi.fn(), ref = createRef<ComposerHandle>()) => {
  render(<Composer ref={ref} disabled={false} vision locked={locked} providerName={null} onSend={onSend} onStop={() => undefined} />);
  return { onSend, ref };
};
const box = () => screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;

describe("Composer while there is no provider", () => {
  it("disables the input, the send button and the tools, and says why", () => {
    view(true);
    expect(box().disabled).toBe(true);
    expect(box().placeholder).toBe("Add a provider to start chatting");
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Search the web" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Attach images" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends nothing from Enter, submit, setText or a file drop", () => {
    const { onSend, ref } = view(true);
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.keyDown(box(), { key: "Enter", ctrlKey: true });
    fireEvent.submit(box().closest("form") as HTMLFormElement);
    act(() => ref.current?.setText("Write a scene where "));
    expect(box().value).toBe("");
    fireEvent.drop(box().closest("form") as HTMLFormElement, { dataTransfer: { types: ["Files"], files: [new File(["x"], "a.png", { type: "image/png" })] } });
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Attached images" })).toBeNull();
  });

  it("is a normal composer once unlocked", () => {
    const { onSend } = view(false);
    expect(box().disabled).toBe(false);
    expect(box().placeholder).toBe("Write a message…");
    fireEvent.change(box(), { target: { value: "hello" } });
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hello", [], false, false);
  });
});
