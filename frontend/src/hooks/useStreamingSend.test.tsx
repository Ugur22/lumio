// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TrialFailure } from "../lib/trial";
import { useStream } from "../store/stream";
import { json, mockFetch } from "../test/helpers";
import { useStreamingSend } from "./useStreamingSend";
import { trialKey } from "./useTrial";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useStream.getState().clear();
});

function setup(onTrialRefused?: (failure: TrialFailure) => void) {
  const client = new QueryClient();
  client.setQueryData(trialKey, { enrolled: true, limit: 5, used: 2, remaining: 3, ended: false });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useStreamingSend({ onTrialRefused }), { wrapper });
  const send = () => act(() => hook.result.current.send("c1", "hello", [], false, false, () => undefined));
  return { client, send };
}

const pending = () => useStream.getState().pending;
const stale = (client: QueryClient) => client.getQueryState(trialKey)?.isInvalidated;

describe("useStreamingSend and the free trial", () => {
  it("shows the trial-ended message as a notice, opens Providers, and refreshes the count on a 402", async () => {
    mockFetch(() => json({ detail: "Your free trial has ended. Add your own provider to continue." }, 402));
    const refused = vi.fn();
    const { client, send } = setup(refused);
    send();
    await waitFor(() => expect(pending()?.status).toBe("error"));
    expect(pending()).toMatchObject({ error: "Your free trial has ended. Add your own provider to continue.", notice: true });
    expect(refused).toHaveBeenCalledWith({ kind: "ended", message: "Your free trial has ended. Add your own provider to continue." });
    await waitFor(() => expect(stale(client)).toBe(true));
  });

  it("shows the trials-are-full message on a 503 without treating it as a fault", async () => {
    mockFetch(() => json({ detail: "Free trials are full today, try tomorrow" }, 503, { "Retry-After": "3600" }));
    const refused = vi.fn();
    const { client, send } = setup(refused);
    send();
    await waitFor(() => expect(pending()?.status).toBe("error"));
    expect(pending()).toMatchObject({ error: "Free trials are full today, try tomorrow", notice: true });
    expect(refused).toHaveBeenCalledWith(expect.objectContaining({ kind: "full" }));
    expect(stale(client)).toBeFalsy();
  });

  it("keeps any other failure a plain error", async () => {
    mockFetch(() => json({ detail: "Upstream exploded" }, 500));
    const refused = vi.fn();
    const { send } = setup(refused);
    send();
    await waitFor(() => expect(pending()?.status).toBe("error"));
    expect(pending()).toMatchObject({ error: "Upstream exploded" });
    expect(pending()).not.toHaveProperty("notice");
    expect(refused).not.toHaveBeenCalled();
  });

  it("refreshes the count when a reply's done event carries trial", async () => {
    const done = { id: "c1", messages: [], title: "t", usage: null, context: {}, trial: { remaining: 2 } };
    mockFetch(
      () => new Response(`event: done\ndata: ${JSON.stringify(done)}\n\n`, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    const { client, send } = setup();
    send();
    await waitFor(() => expect(stale(client)).toBe(true));
  });

  it("leaves the count alone for a reply without trial", async () => {
    const done = { id: "c1", messages: [], title: "t", usage: null, context: {} };
    mockFetch(
      () => new Response(`event: done\ndata: ${JSON.stringify(done)}\n\n`, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    const { client, send } = setup();
    send();
    await waitFor(() => expect(pending()).toBeNull());
    expect(stale(client)).toBeFalsy();
  });
});
