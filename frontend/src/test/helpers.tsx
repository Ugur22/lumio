import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { useSession } from "../store/session";

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

export const noContent = () => new Response(null, { status: 204 });

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

export function mockFetch(handler: Handler) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(handler(String(input), init)));
  vi.stubGlobal("fetch", fn);
  return fn;
}

// jsdom has no matchMedia; useTheme and the sidebar ask for it.
export function stubMatchMedia() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

// Headless UI's menus and dialogs observe their size.
export function stubResizeObserver() {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
}

export const resetSession = () => useSession.setState({ status: "pending", user: null, notice: null });

export function renderWithClient(ui: ReactElement, client = new QueryClient()) {
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

export const alice = { id: "u1", username: "alice", is_admin: false };
export const localUser = { id: "local", username: "local", is_admin: true };

export function bodyOf(fn: ReturnType<typeof mockFetch>, path: string): Record<string, unknown> | undefined {
  const call = fn.mock.calls.find(([url]) => String(url) === path);
  const body = call?.[1]?.body;
  return typeof body === "string" ? (JSON.parse(body) as Record<string, unknown>) : undefined;
}
