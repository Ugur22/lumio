// @vitest-environment jsdom
import { QueryClient } from "@tanstack/react-query";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Profile, TrialStatus } from "../types";
import { json, mockFetch, renderWithClient, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { ProvidersDialog } from "./ProvidersDialog";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const trialProfile = {
  id: "trial",
  name: "internal-trial-name",
  base_url: "https://managed.example/v1",
  model: "deepseek-flash",
  needs_key: false,
  configured: true,
  last4: null,
  source: "server",
  key_store: "keychain",
  vision: false,
  image_model: null,
  context_window: null,
  managed: true,
} satisfies Profile;
const ownProfile = { ...trialProfile, id: "own", name: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama", needs_key: true, last4: "wxyz", source: "keychain", managed: false } satisfies Profile;

const running: TrialStatus = { enrolled: true, limit: 5, used: 2, remaining: 3, ended: false };
const ended: TrialStatus = { enrolled: true, limit: 5, used: 5, remaining: 0, ended: true };

function open(trial: TrialStatus, profiles: Profile[] = [trialProfile]) {
  mockFetch((url) => {
    if (url === "/api/profiles") return json({ active: profiles[0]?.id ?? null, profiles });
    if (url === "/api/trial") return json(trial);
    if (url === "/api/web") return json({ configured: false, key_store: "keychain", last4: null });
    return json({}, 404);
  });
  return renderWithClient(<ProvidersDialog open onClose={() => undefined} />, new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }));
}

const addButton = () => screen.getByRole("button", { name: /Add provider/ }) as HTMLButtonElement;

describe("ProvidersDialog during the free trial", () => {
  it("shows the managed profile read-only under the label Free trial", async () => {
    open(running);
    expect(await screen.findByText("Free trial")).toBeTruthy();
    expect(screen.getByText(/3 of 5 free messages left/)).toBeTruthy();
    expect(screen.queryByText("internal-trial-name")).toBeNull();
    expect(screen.queryByText(/managed\.example/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("disables Add provider and the web key, and says why", async () => {
    open(running);
    await screen.findByText("Free trial");
    await waitFor(() => expect(addButton().disabled).toBe(true));
    expect(addButton().getAttribute("aria-describedby")).toBe("add-provider-locked");
    expect(screen.getByText("Adding your own provider unlocks when your free trial ends.")).toBeTruthy();
    const tavily = await screen.findByLabelText("Tavily API key");
    expect((tavily as HTMLInputElement).disabled).toBe(true);
  });

  it("enables both once the trial has ended, and keeps the managed row read-only", async () => {
    open(ended);
    await screen.findByText("Free trial");
    await waitFor(() => expect(screen.getByText(/Free trial ended/)).toBeTruthy());
    expect(addButton().disabled).toBe(false);
    expect(screen.queryByText("Adding your own provider unlocks when your free trial ends.")).toBeNull();
    expect((screen.getByLabelText("Tavily API key") as HTMLInputElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("changes nothing for someone without a trial", async () => {
    open({ enrolled: false, limit: 0, used: 0, remaining: 0, ended: false }, [ownProfile]);
    expect(await screen.findByText("Groq")).toBeTruthy();
    expect(addButton().disabled).toBe(false);
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("lists the managed profile read-only next to the user's own after the trial", async () => {
    open(ended, [trialProfile, ownProfile]);
    expect(await screen.findByText("Groq")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
  });
});
