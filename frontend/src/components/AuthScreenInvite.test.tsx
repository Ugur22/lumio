// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetInviteLink } from "../store/invite";
import { json, mockFetch, resetSession, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { AuthScreen } from "./AuthScreen";

beforeEach(() => {
  resetSession();
  resetInviteLink();
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const arrive = (hash: string) => window.history.replaceState(null, "", `/${hash}`);
const href = (name: string) => (screen.getByRole("link", { name }) as HTMLAnchorElement).getAttribute("href");

describe("invite link on the sign-in screen", () => {
  it("clears the fragment, checks once, and carries a trial invite to Google and GitHub", async () => {
    const fetchMock = mockFetch(() => json({ valid: true, kind: "trial", reason: null }));
    arrive("#invite=abc123");
    const { rerender } = render(<AuthScreen />);
    expect(window.location.hash).toBe("");
    expect(await screen.findByText("Invite applied")).toBeTruthy();
    expect(screen.getByText("Sign in to start free")).toBeTruthy();
    expect(href("Continue with Google")).toBe("/api/auth/oauth/google/start?invite=abc123");
    expect(href("Continue with GitHub")).toBe("/api/auth/oauth/github/start?invite=abc123");
    rerender(<AuthScreen />);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ invite: "abc123" });
  });

  it("opens the registration form with the invite filled in for an account invite", async () => {
    mockFetch(() => json({ valid: true, kind: "account", reason: null }));
    arrive("#invite=acct-1");
    render(<AuthScreen />);
    expect(await screen.findByText("Create your account")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("tab", { name: "Create account" }).getAttribute("aria-selected")).toBe("true"));
    expect((screen.getByLabelText("Invite code") as HTMLInputElement).value).toBe("acct-1");
    expect(screen.getByText("At least 10 characters")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
  });

  it("removes the invite with the x button", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ valid: true, kind: "trial", reason: null }));
    arrive("#invite=abc123");
    render(<AuthScreen />);
    await user.click(await screen.findByRole("button", { name: "Remove invite" }));
    expect(screen.queryByText("Invite applied")).toBeNull();
    expect(href("Continue with Google")).toBe("/api/auth/oauth/google/start");
  });

  it.each([
    ["used", "This invite was already used. Ask for a new one."],
    ["expired", "This invite has expired. Ask for a new one."],
    ["revoked", "This invite was cancelled. Ask for a new one."],
    ["unknown", "This invite isn't valid. Check the link or ask for a new one."],
  ])("explains a %s invite in an alert and falls back to plain sign-in", async (reason, text) => {
    mockFetch(() => json({ valid: false, kind: null, reason }));
    arrive("#invite=bad");
    render(<AuthScreen />);
    expect((await screen.findByText(text)).closest('[role="alert"]')).not.toBeNull();
    expect(href("Continue with Google")).toBe("/api/auth/oauth/google/start");
    expect(screen.getByRole("tab", { name: "Sign in" }).getAttribute("aria-selected")).toBe("true");
  });

  it("keeps the code usable when the check is throttled", async () => {
    mockFetch(() => json({ detail: "slow down" }, 429, { "Retry-After": "600" }));
    arrive("#invite=abc123");
    render(<AuthScreen />);
    expect(await screen.findByText(/Too many checks/)).toBeTruthy();
    expect(href("Continue with Google")).toBe("/api/auth/oauth/google/start?invite=abc123");
  });

  it("makes no request and shows no card without an invite in the address", () => {
    const fetchMock = mockFetch(() => json({}));
    render(<AuthScreen />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Invite applied")).toBeNull();
  });
});
