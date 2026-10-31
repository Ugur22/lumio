// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../store/session";
import { alice, bodyOf, json, mockFetch, resetSession, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { AuthScreen } from "./AuthScreen";

beforeEach(() => {
  resetSession();
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

async function fillSignIn(user: ReturnType<typeof userEvent.setup>, name = "Alice", password = "wrong-password") {
  await user.type(field("Username"), name);
  await user.type(field("Password"), password);
}

async function openRegister(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: "Create account" }));
}

async function fillRegister(user: ReturnType<typeof userEvent.setup>) {
  await user.type(field("Invite code"), " INV-123 ");
  await user.type(field("Username"), "Bob_1");
  await user.type(field("Password"), "correct horse battery");
}

describe("AuthScreen", () => {
  it("offers Sign in and Create account as tabs, with sign in first", () => {
    render(<AuthScreen />);
    expect(screen.getByRole("tablist")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Sign in" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Create account" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("tabpanel")).toBeTruthy();
  });

  it("labels the sign-in fields and sets their autocomplete", () => {
    render(<AuthScreen />);
    expect(field("Username").getAttribute("autocomplete")).toBe("username");
    expect(field("Password").getAttribute("autocomplete")).toBe("current-password");
    expect(field("Password").type).toBe("password");
  });

  it("labels the register fields, requires an invite, and uses new-password", async () => {
    const user = userEvent.setup();
    render(<AuthScreen />);
    await openRegister(user);
    expect(field("Invite code").required).toBe(true);
    expect(field("Username").getAttribute("autocomplete")).toBe("username");
    expect(field("Password").getAttribute("autocomplete")).toBe("new-password");
    expect(screen.getByRole("button", { name: "Create account" })).toBeTruthy();
  });

  it("moves focus into the new tab's first field when the tab is switched", async () => {
    const user = userEvent.setup();
    render(<AuthScreen />);
    expect(document.activeElement).not.toBe(field("Username"));
    await openRegister(user);
    expect(document.activeElement).toBe(field("Invite code"));
    await user.click(screen.getByRole("tab", { name: "Sign in" }));
    expect(document.activeElement).toBe(field("Username"));
  });

  it("shows the notice left by a lost session", () => {
    useSession.setState({ notice: "Your session has ended. Sign in again." });
    render(<AuthScreen />);
    expect(screen.getByRole("status").textContent).toContain("session has ended");
  });
});

describe("sign in", () => {
  it("signs in with Enter, sends the lowercased name, and clears the password", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => json(alice));
    render(<AuthScreen />);
    await user.type(field("Username"), "Alice");
    await user.type(field("Password"), "a-long-password{Enter}");
    await waitFor(() => expect(useSession.getState().user).toEqual(alice));
    expect(useSession.getState().status).toBe("signedIn");
    expect(bodyOf(fetchMock, "/api/auth/login")).toEqual({ username: "alice", password: "a-long-password" });
    expect(field("Password").value).toBe("");
  });

  it("disables the submit button while the request is pending", async () => {
    const user = userEvent.setup();
    let answer: (r: Response) => void = () => undefined;
    const fetchMock = mockFetch(() => new Promise<Response>((resolve) => (answer = resolve)));
    render(<AuthScreen />);
    await fillSignIn(user);
    await user.keyboard("{Enter}");
    const button = screen.getByRole("button", { name: /please wait/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await user.keyboard("{Enter}");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => answer(json({ detail: "Invalid username or password" }, 401)));
    expect((screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a 401 inline as an alert and puts the cursor in the password field", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "Invalid username or password" }, 401));
    render(<AuthScreen />);
    await fillSignIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Invalid username or password");
    expect(document.activeElement).toBe(field("Password"));
    expect(useSession.getState().status).toBe("pending");
  });

  it("words a 429 from Retry-After in seconds", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "Too many failed attempts; try again later" }, 429, { "Retry-After": "45" }));
    render(<AuthScreen />);
    await fillSignIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Too many attempts, try again in 45 seconds");
  });

  it("words a 429 from Retry-After in minutes", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "x" }, 429, { "Retry-After": "600" }));
    render(<AuthScreen />);
    await fillSignIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Too many attempts, try again in 10 minutes");
  });

  it("explains a network failure", async () => {
    const user = userEvent.setup();
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    render(<AuthScreen />);
    await fillSignIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/reach the server/);
  });
});

describe("create account", () => {
  it("registers with a trimmed invite and lowercased name, then clears the secrets", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => json(alice, 201));
    render(<AuthScreen />);
    await openRegister(user);
    await fillRegister(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(useSession.getState().status).toBe("signedIn"));
    expect(bodyOf(fetchMock, "/api/auth/register")).toEqual({
      username: "bob_1",
      password: "correct horse battery",
      invite: "INV-123",
    });
    expect(field("Password").value).toBe("");
    expect(field("Invite code").value).toBe("");
  });

  it.each([
    ["403", 403, "That invite is not valid", "Invite code"],
    ["409", 409, "That username is taken", "Username"],
  ])("shows a %s inline and focuses the field to fix", async (_n, status, detail, label) => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail }, status));
    render(<AuthScreen />);
    await openRegister(user);
    await fillRegister(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toBe(detail);
    expect(document.activeElement).toBe(field(label));
    expect(useSession.getState().status).toBe("pending");
  });

  it("shows the server's 422 message and focuses the first field the hints fault", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: [{ msg: "String should have at least 10 characters", loc: ["body", "password"] }] }, 422));
    render(<AuthScreen />);
    await openRegister(user);
    await user.type(field("Invite code"), "inv");
    await user.type(field("Username"), "bob");
    await user.type(field("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toBe("String should have at least 10 characters");
    expect(document.activeElement).toBe(field("Password"));
  });

  it("words a 429 from Retry-After", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "x" }, 429, { "Retry-After": "1" }));
    render(<AuthScreen />);
    await openRegister(user);
    await fillRegister(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Too many attempts, try again in 1 second");
  });

  it("hints at the rules once a field has been left, without blocking the server", async () => {
    const user = userEvent.setup();
    render(<AuthScreen />);
    await openRegister(user);
    await user.type(field("Username"), "a b");
    await user.tab();
    expect(field("Username").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(/3-32 characters/)).toBeTruthy();
  });
});
