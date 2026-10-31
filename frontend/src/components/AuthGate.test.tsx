// @vitest-environment jsdom
import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { useStream } from "../store/stream";
import { useSession } from "../store/session";
import { USER_STORAGE_PREFIX } from "../lib/auth";
import { alice, json, localUser, mockFetch, noContent, renderWithClient, resetSession, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { AuthGate } from "./AuthGate";
import { UserMenu } from "./UserMenu";

function Probe() {
  return (
    <div>
      <p>the app</p>
      <button type="button" onClick={() => void api.listChats().catch(() => undefined)}>
        load chats
      </button>
      <UserMenu />
    </div>
  );
}

beforeEach(() => {
  resetSession();
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  useStream.getState().clear();
});

describe("AuthGate", () => {
  it("shows a neutral loading state, never the login screen, while /me is pending", async () => {
    let answer: (r: Response) => void = () => undefined;
    mockFetch(() => new Promise<Response>((resolve) => (answer = resolve)));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    expect(screen.getByRole("status").textContent).toContain("Loading");
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByText("the app")).toBeNull();
    await act(async () => answer(json(alice)));
    expect(await screen.findByText("the app")).toBeTruthy();
  });

  it("shows the login screen on 401", async () => {
    mockFetch(() => json({ detail: "Not signed in" }, 401));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("renders the app for a signed-in user, with their menu", async () => {
    mockFetch(() => json(alice));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    expect(await screen.findByText("the app")).toBeTruthy();
    expect(screen.getByRole("button", { name: /alice/ })).toBeTruthy();
  });

  it("renders the app for the local user without a menu or login", async () => {
    mockFetch(() => json(localUser));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    expect(await screen.findByText("the app")).toBeTruthy();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("button", { name: /local|sign out/i })).toBeNull();
  });

  it("offers a retry when the server cannot be reached", async () => {
    let up = false;
    mockFetch(() => (up ? json(alice) : Promise.reject(new TypeError("Failed to fetch"))));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    expect((await screen.findByRole("alert")).textContent).toContain("Could not reach the server");
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("the app")).toBeTruthy();
  });
});

describe("session loss and sign-out", () => {
  it("drops to the login screen with a notice when a request returns 401", async () => {
    mockFetch((url) => (url === "/api/auth/me" ? json(alice) : json({ detail: "Not signed in" }, 401)));
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "load chats" }));
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Your session has ended");
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("drops to the login screen when the streaming send returns 401, without throwing", async () => {
    mockFetch((url) => (url === "/api/auth/me" ? json(alice) : json({ detail: "Not signed in" }, 401)));
    let sent: Promise<unknown> = Promise.resolve();
    function Sender() {
      return (
        <button
          type="button"
          onClick={() => {
            sent = api
              .sendMessage("c1", "hi", {
                images: [],
                web: false,
                illustrate: false,
                signal: new AbortController().signal,
                onDelta: () => undefined,
                onSources: () => undefined,
                onIllustrationFailed: () => undefined,
              })
              .catch((e: unknown) => e);
          }}
        >
          send
        </button>
      );
    }
    renderWithClient(
      <AuthGate>
        <Sender />
      </AuthGate>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "send" }));
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeTruthy();
    expect(await sent).toMatchObject({ status: 401 });
  });

  it("aborts a stream in flight when the app unmounts on session loss", async () => {
    const { useStreamingSend } = await import("../hooks/useStreamingSend");
    let signal: AbortSignal | undefined;
    mockFetch((url, init) => {
      if (url === "/api/auth/me") return json(alice);
      signal = init?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    });
    function Chatty() {
      const { send } = useStreamingSend();
      return (
        <button type="button" onClick={() => send("c1", "hi", [], false, false, () => undefined)}>
          chat
        </button>
      );
    }
    renderWithClient(
      <AuthGate>
        <Chatty />
      </AuthGate>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "chat" }));
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal?.aborted).toBe(false);
    act(() => useSession.getState().expire());
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(useStream.getState().pending).toBeNull());
  });

  it("does not drop to login on a wrong login or a 400 from the password change", async () => {
    mockFetch((url) => {
      if (url === "/api/auth/me") return json(alice);
      if (url === "/api/auth/password") return json({ detail: "Current password is incorrect" }, 400);
      return json({ detail: "Invalid username or password" }, 401);
    });
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
    );
    await screen.findByText("the app");
    await expect(api.login({ username: "a", password: "b" })).rejects.toMatchObject({ status: 401 });
    await expect(api.changePassword({ current_password: "x", new_password: "y" })).rejects.toMatchObject({ status: 400 });
    expect(useSession.getState().status).toBe("signedIn");
    expect(screen.getByText("the app")).toBeTruthy();
  });

  it("clears the previous user's cached data, stream state and per-user storage on sign-out", async () => {
    mockFetch((url) => (url === "/api/auth/me" ? json(alice) : noContent()));
    const client = new QueryClient();
    client.setQueryData(["chats"], [{ id: "c1", title: "alice's secret" }]);
    client.setQueryData(["profiles"], { profiles: [] });
    localStorage.setItem(`${USER_STORAGE_PREFIX}draft`, "private words");
    localStorage.setItem("theme", "dark");
    useStream.getState().start("c1", "half-typed reply", []);
    renderWithClient(
      <AuthGate>
        <Probe />
      </AuthGate>,
      client,
    );
    await userEvent.click(await screen.findByRole("button", { name: /alice/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /sign out/i }));
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeTruthy();
    await waitFor(() => expect(client.getQueryCache().getAll()).toHaveLength(0));
    expect(useStream.getState().pending).toBeNull();
    expect(localStorage.getItem(`${USER_STORAGE_PREFIX}draft`)).toBeNull();
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(screen.queryByText("alice")).toBeNull();
  });
});
