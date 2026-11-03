// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, mockFetch, renderWithClient, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { ReplicateSection } from "./ProvidersDialog";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const putBody = (fn: ReturnType<typeof mockFetch>) =>
  JSON.parse(String(fn.mock.calls.find(([, init]) => init?.method === "PUT")?.[1]?.body)) as unknown;

const none = { configured: false, last4: null };
const set = { configured: true, last4: "abcd" };

describe("ReplicateSection", () => {
  it("explains the missing key, the cost and where the prompt goes", async () => {
    mockFetch(() => json(none));
    renderWithClient(<ReplicateSection />);
    expect(await screen.findByText(/No Replicate key\. Illustrate with a replicate: image model needs one\./)).toBeTruthy();
    expect(screen.getByText(/about \$0\.06 for the Flux model.*prompt is sent to Replicate/)).toBeTruthy();
    expect(screen.getByLabelText("Replicate API key")).toBeTruthy();
  });

  it("saves a typed key, clears the field and shows the last four", async () => {
    const user = userEvent.setup();
    const fetchFn = mockFetch((_url, init) => (init?.method === "PUT" ? json(set) : json(none)));
    renderWithClient(<ReplicateSection />);
    const input = (await screen.findByLabelText("Replicate API key")) as HTMLInputElement;
    await user.type(input, "  r8_secret  ");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Key ending in ••••abcd")).toBeTruthy();
    expect(putBody(fetchFn)).toEqual({ key: "r8_secret" });
    expect(screen.queryByLabelText("Replicate API key")).toBeNull();
  });

  it("replaces a saved key", async () => {
    const user = userEvent.setup();
    const fetchFn = mockFetch((_url, init) => (init?.method === "PUT" ? json({ configured: true, last4: "wxyz" }) : json(set)));
    renderWithClient(<ReplicateSection />);
    await user.click(await screen.findByRole("button", { name: "Replace" }));
    await user.type(screen.getByLabelText("Replicate API key"), "r8_new");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Key ending in ••••wxyz")).toBeTruthy();
    expect(putBody(fetchFn)).toEqual({ key: "r8_new" });
    expect(screen.queryByLabelText("Replicate API key")).toBeNull();
  });

  it("removes the key", async () => {
    const user = userEvent.setup();
    const fetchFn = mockFetch((_url, init) => (init?.method === "DELETE" ? json(none) : json(set)));
    renderWithClient(<ReplicateSection />);
    await user.click(await screen.findByRole("button", { name: /Remove/ }));
    expect(await screen.findByText(/No Replicate key/)).toBeTruthy();
    expect(fetchFn.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  });

  it("shows the server's failure message", async () => {
    const user = userEvent.setup();
    mockFetch((_url, init) => (init?.method === "PUT" ? json({ detail: "Replicate rejected the key" }, 400) : json(none)));
    renderWithClient(<ReplicateSection />);
    await user.type(await screen.findByLabelText("Replicate API key"), "bad");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Replicate rejected the key");
  });
});
