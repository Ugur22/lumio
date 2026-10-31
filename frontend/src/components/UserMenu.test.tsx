// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store/session";
import { alice, bodyOf, json, localUser, mockFetch, noContent, resetSession, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { UserMenu } from "./UserMenu";

beforeEach(() => {
  resetSession();
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /alice/ }));
  await user.click(await screen.findByRole("menuitem", { name: /change password/i }));
  return screen.findByRole("dialog");
}

const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

async function fillPasswords(user: ReturnType<typeof userEvent.setup>, confirm = "brand-new-secret") {
  await user.type(field("Current password"), "old-password-1");
  await user.type(field("New password"), "brand-new-secret");
  await user.type(field("Confirm new password"), confirm);
}

describe("UserMenu", () => {
  it("renders nothing for the local user", () => {
    useSession.getState().signIn(localUser);
    const { container } = render(<UserMenu />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing before anyone is signed in", () => {
    const { container } = render(<UserMenu />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the username and offers Change password and Sign out", async () => {
    const user = userEvent.setup();
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await user.click(screen.getByRole("button", { name: /alice/ }));
    expect(await screen.findByRole("menuitem", { name: /change password/i })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toBeTruthy();
  });

  it("signs out through the API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => noContent());
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await user.click(screen.getByRole("button", { name: /alice/ }));
    await user.click(await screen.findByRole("menuitem", { name: /sign out/i }));
    await waitFor(() => expect(useSession.getState().status).toBe("anonymous"));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/logout");
    expect(useSession.getState().user).toBeNull();
  });

  it("stays signed in and says so when sign-out fails", async () => {
    const user = userEvent.setup();
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await user.click(screen.getByRole("button", { name: /alice/ }));
    await user.click(await screen.findByRole("menuitem", { name: /sign out/i }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/reach the server/);
    expect(useSession.getState().status).toBe("signedIn");
  });
});

describe("Change password dialog", () => {
  it("labels three password fields with the right autocomplete", async () => {
    const user = userEvent.setup();
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    const dialog = await openDialog(user);
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(field("Current password").getAttribute("autocomplete")).toBe("current-password");
    expect(field("New password").getAttribute("autocomplete")).toBe("new-password");
    expect(field("Confirm new password").getAttribute("autocomplete")).toBe("new-password");
  });

  it("changes the password, confirms, and clears the fields", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => noContent());
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await openDialog(user);
    await fillPasswords(user);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("status")).textContent).toContain("Password changed");
    expect(bodyOf(fetchMock, "/api/auth/password")).toEqual({
      current_password: "old-password-1",
      new_password: "brand-new-secret",
    });
    expect(screen.queryByLabelText("New password")).toBeNull();
    expect(useSession.getState().status).toBe("signedIn");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does not send when the confirmation differs", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => noContent());
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await openDialog(user);
    await fillPasswords(user, "something-else-entirely");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findAllByRole("alert"))[0]?.textContent).toMatch(/do not match/);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field("Confirm new password"));
  });

  it("shows a wrong current password (400) inline and stays signed in", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "Current password is incorrect" }, 400));
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await openDialog(user);
    await fillPasswords(user);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(screen.getAllByRole("alert").some((a) => a.textContent === "Current password is incorrect")).toBe(true));
    expect(document.activeElement).toBe(field("Current password"));
    expect(useSession.getState().status).toBe("signedIn");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("words a 429 from Retry-After", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "x" }, 429, { "Retry-After": "120" }));
    useSession.getState().signIn(alice);
    render(<UserMenu />);
    await openDialog(user);
    await fillPasswords(user);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() =>
      expect(screen.getAllByRole("alert").some((a) => a.textContent === "Too many attempts, try again in 2 minutes")).toBe(true),
    );
  });
});
