// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubResizeObserver } from "../test/helpers";
import type { ChatSummary } from "../types";
import { Sidebar } from "./Sidebar";

const chat: ChatSummary = { id: "c1", title: "Dragon story", updated: new Date().toISOString() } as ChatSummary;

function stubPhone(phone: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: phone && query.includes("max-width"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  stubResizeObserver();
}

function setup(over: { open?: boolean; chats?: ChatSummary[] } = {}) {
  const fns = { onRename: vi.fn(), onDelete: vi.fn(), onOpenChange: vi.fn(), onToggleTheme: vi.fn() };
  render(
    <Sidebar
      chats={over.chats ?? [chat]}
      currentId={null}
      open={over.open ?? false}
      theme="light"
      onNew={() => undefined}
      onOpen={() => undefined}
      onOpenSettings={() => undefined}
      {...fns}
    />,
  );
  return fns;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Sidebar chat actions", () => {
  it("shows one more-actions button on a phone, whose sheet offers Rename and Delete", async () => {
    stubPhone(true);
    const { onRename, onDelete } = setup();
    expect(screen.queryByRole("button", { name: "Rename Dragon story" })).toBeNull();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions for Dragon story" }));
    await user.click(await screen.findByRole("button", { name: /rename/i }));
    expect(onRename).toHaveBeenCalledWith(chat);

    // The sheet slides out before it unmounts, and the page behind it stays inert until then.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Actions for Dragon story" }));
    await user.click(await screen.findByRole("button", { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith(chat);
  });

  it("keeps the inline rename and delete buttons on desktop", async () => {
    stubPhone(false);
    setup();
    expect(await screen.findByRole("button", { name: "Rename Dragon story" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Actions for Dragon story" })).toBeNull();
  });
});

describe("Sidebar swipe", () => {
  const touch = (type: string, x: number, y = 100) =>
    fireEvent(document, Object.assign(new Event(type, { bubbles: true }), { touches: type === "touchend" ? [] : [{ clientX: x, clientY: y }], changedTouches: [{ clientX: x, clientY: y }] }));

  it("opens on an edge swipe and closes on a swipe left, on phones only", () => {
    stubPhone(true);
    const closed = setup();
    touch("touchstart", 5);
    touch("touchend", 120);
    expect(closed.onOpenChange).toHaveBeenCalledWith(true);
    cleanup();

    const opened = setup({ open: true });
    touch("touchstart", 200);
    touch("touchend", 100);
    expect(opened.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("ignores swipes on desktop", () => {
    stubPhone(false);
    const { onOpenChange } = setup();
    touch("touchstart", 5);
    touch("touchend", 120);
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

describe("Sidebar list", () => {
  it("keeps rows at full height so a long list scrolls instead of squeezing them", () => {
    stubPhone(true);
    setup();
    const row = screen.getByRole("navigation", { name: "Saved chats" }).firstElementChild;
    expect(row?.classList.contains("shrink-0")).toBe(true);
  });

  it("shows an empty state when there are no chats", () => {
    stubPhone(false);
    setup({ chats: [] });
    expect(screen.getByText("No chats yet")).toBeTruthy();
  });
});

describe("Sidebar theme switch", () => {
  it("shows the current theme and switches only when the other side is picked", async () => {
    stubPhone(false);
    const { onToggleTheme } = setup();
    expect(screen.getByRole("radio", { name: "Light" }).getAttribute("aria-checked")).toBe("true");
    await userEvent.click(screen.getByRole("radio", { name: "Light" }));
    expect(onToggleTheme).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(onToggleTheme).toHaveBeenCalledTimes(1);
  });
});
