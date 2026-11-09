// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { json, mockFetch, renderWithClient, stubMatchMedia, stubResizeObserver } from "./test/helpers";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
  vi.stubGlobal("scrollTo", () => undefined);
  Element.prototype.scrollTo = () => undefined;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function view(profiles: unknown, trial: unknown) {
  mockFetch((url) => {
    if (url.endsWith("/trial")) return json(trial);
    if (url.includes("/profiles")) return json(profiles);
    if (url.includes("/chats")) return json([]);
    return json({});
  });
  return renderWithClient(<App />);
}
const box = () => screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;

describe("App without a provider", () => {
  it("locks the composer and hides the starters and the story line", async () => {
    view({ active: null, profiles: [] }, { enrolled: false });
    await screen.findByRole("heading", { name: "Connect a provider to start chatting" });
    expect(box().disabled).toBe(true);
    expect(box().placeholder).toBe("Add a provider to start chatting");
    expect(screen.queryByText("Open a story")).toBeNull();
    expect(screen.queryByRole("button", { name: "Set up your story" })).toBeNull();
  });

  it("keeps the composer and starters once a provider exists", async () => {
    view({ active: "a", profiles: [{ id: "a", name: "a", managed: false }] }, { enrolled: false });
    await screen.findByRole("heading", { name: "What shall we write?" });
    await vi.waitFor(() => expect(screen.getByText("Open a story")).toBeTruthy());
    expect(box().disabled).toBe(false);
    expect(screen.getByRole("button", { name: "Set up your story" })).toBeTruthy();
  });
});
