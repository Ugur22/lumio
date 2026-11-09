// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, mockFetch, renderWithClient } from "../test/helpers";
import { FirstRun, Onboarding } from "./FirstRun";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const view = (profiles: unknown, trial: unknown = { enrolled: false }, onManage = () => undefined) => {
  mockFetch((url) => (url.endsWith("/trial") ? json(trial) : json(profiles)));
  return renderWithClient(<FirstRun onManage={onManage} fallback={<h2>What shall we write?</h2>} />);
};

const empty = { active: null, profiles: [] };

describe("FirstRun", () => {
  it("shows the onboarding for a new account and opens Providers", async () => {
    const user = userEvent.setup();
    const manage = vi.fn();
    view(empty, { enrolled: false }, manage);
    expect(await screen.findByRole("heading", { name: "Connect a provider to start chatting" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText(/never in this browser/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add a provider" }));
    expect(manage).toHaveBeenCalledTimes(1);
  });

  it("shows the short ended copy without steps", async () => {
    view({ active: "m", profiles: [{ id: "m", name: "m", managed: true }] }, { enrolled: true, limit: 5, used: 5, remaining: 0, ended: true });
    expect(await screen.findByRole("heading", { name: "Your free trial has ended" })).toBeTruthy();
    expect(screen.getByText(/chats are still here/)).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("shows the normal welcome while loading", () => {
    mockFetch(() => new Promise<Response>(() => undefined) as unknown as Response);
    renderWithClient(<FirstRun onManage={() => undefined} fallback={<h2>What shall we write?</h2>} />);
    expect(screen.getByRole("heading", { name: "What shall we write?" })).toBeTruthy();
  });

  it("shows the normal welcome once a provider exists", async () => {
    const { client } = view({ active: "a", profiles: [{ id: "a", name: "a", managed: false }] });
    await vi.waitFor(() => {
      expect(client.getQueryData(["profiles"])).toBeDefined();
      expect(client.getQueryData(["trial"])).toBeDefined();
    });
    expect(screen.getByRole("heading", { name: "What shall we write?" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a provider" })).toBeNull();
  });
});

describe("Onboarding", () => {
  it("hides the decorative icon from assistive tech", () => {
    const { container } = renderWithClient(<Onboarding kind="new" onManage={() => undefined} />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
});
