// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InviteItem } from "../types";
import { json, mockFetch, noContent, renderWithClient, stubMatchMedia, stubResizeObserver } from "../test/helpers";
import { InvitesDialog } from "./InvitesDialog";

beforeEach(() => {
  stubMatchMedia();
  stubResizeObserver();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DAY = 86_400_000;
const iso = (days: number) => new Date(Date.now() + days * DAY).toISOString();

const unused: InviteItem = { id: "u1", kind: "trial", note: "Mia", created: iso(-1), expires: iso(5), status: "unused", used_at: null };
const soon: InviteItem = { ...unused, id: "u2", note: "Sam", expires: iso(1) };
const used: InviteItem = { ...unused, id: "d1", kind: "account", note: "Lee", status: "used", used_at: iso(-2) };
const expired: InviteItem = { ...unused, id: "e1", kind: "account", note: "Zoe", status: "expired", expires: iso(-1) };
const revoked: InviteItem = { ...unused, id: "r1", note: null, status: "revoked" };

function serve(list: InviteItem[], extra?: (url: string, init?: RequestInit) => Response | undefined) {
  return mockFetch((url, init) => {
    const custom = extra?.(url, init);
    if (custom) return custom;
    if (url === "/api/admin/invites" && (init?.method ?? "GET") === "GET") return json(list);
    return json({ detail: "unexpected" }, 500);
  });
}

const row = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

async function openList(list: InviteItem[], extra?: Parameters<typeof serve>[1]) {
  const fetchMock = serve(list, extra);
  const user = userEvent.setup();
  renderWithClient(<InvitesDialog open onClose={() => undefined} />);
  await waitFor(() => expect(screen.queryByRole("table") ?? screen.queryByText("No invites here.")).toBeTruthy());
  return { user, fetchMock };
}

describe("Invites list", () => {
  it("shows each invite with a word status and the right action", async () => {
    await openList([unused, soon, used, expired, revoked]);
    expect(within(row("Mia")).getByText("Unused")).toBeTruthy();
    expect(within(row("Mia")).getByText("in 5 days")).toBeTruthy();
    expect(within(row("Mia")).getByText("Free trial")).toBeTruthy();
    expect(within(row("Sam")).getByText("Ends soon")).toBeTruthy();
    expect(within(row("Sam")).getByText("tomorrow")).toBeTruthy();
    expect(within(row("Lee")).getByText("Used")).toBeTruthy();
    expect(within(row("Zoe")).getByText("Expired")).toBeTruthy();
    expect(within(row("No note")).getByText("Revoked")).toBeTruthy();

    expect(within(row("Mia")).getByRole("button", { name: /^Revoke/ })).toBeTruthy();
    expect(within(row("Sam")).getByRole("button", { name: /^Revoke/ })).toBeTruthy();
    expect(within(row("Zoe")).getByRole("button", { name: /Create a new/ })).toBeTruthy();
    expect(within(row("Lee")).queryByRole("button")).toBeNull();
    expect(within(row("No note")).queryByRole("button")).toBeNull();
  });

  it("counts on the filter chips and narrows the table", async () => {
    const { user } = await openList([unused, soon, used, expired, revoked]);
    expect(screen.getByRole("button", { name: "All 5" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unused 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Used 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Expired 2" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Expired 2" }));
    expect(screen.getByRole("button", { name: "Expired 2" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("Mia")).toBeNull();
    expect(screen.getByText("Zoe")).toBeTruthy();
    expect(screen.getByText("No note")).toBeTruthy();
  });

  it("renders a note as plain text, never as markup", async () => {
    await openList([{ ...unused, note: "<img src=x onerror=alert(1)><b>hi</b>" }]);
    expect(screen.getByText("<img src=x onerror=alert(1)><b>hi</b>")).toBeTruthy();
    expect(document.querySelector("table img, table b")).toBeNull();
  });

  it("says the code cannot be shown again", async () => {
    await openList([]);
    expect(screen.getByText(/can't be shown again after it is created/)).toBeTruthy();
  });
});

describe("Create and ready", () => {
  const made = { id: "n1", code: "SECRET-CODE", kind: "account", note: "Ada", created: iso(0), expires: iso(7) };
  const create = (url: string, init?: RequestInit) =>
    url === "/api/admin/invites" && init?.method === "POST" ? json(made, 201) : undefined;

  it("creates an account invite and shows the link once", async () => {
    const { user, fetchMock } = await openList([], create);
    await user.click(screen.getByRole("button", { name: "Create invite" }));
    const note = (await screen.findByLabelText("Who is it for? (optional)")) as HTMLInputElement;
    expect(note.maxLength).toBe(80);
    expect(screen.getByText("The link works for 7 days.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Free trial/ }).getAttribute("aria-checked")).toBe("true");
    await user.type(note, "Ada");
    await user.click(screen.getByRole("radio", { name: /Account/ }));
    const dialog = screen.getAllByRole("dialog").at(-1) as HTMLElement;
    await user.click(within(dialog).getByRole("button", { name: "Create invite" }));

    const link = (await screen.findByLabelText("Invite link")) as HTMLInputElement;
    const post = fetchMock.mock.calls.find(([, i]) => i?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ kind: "account", note: "Ada" });
    expect(link.value).toBe(`${window.location.origin}/#invite=SECRET-CODE`);
    expect(screen.getByText(/works once and can't be shown again/)).toBeTruthy();
    expect(screen.getByText(/Send it to Ada yourself/)).toBeTruthy();
  });

  it("confirms a copy with a status, and says so when the clipboard refuses", async () => {
    const { user } = await openList([], create);
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByRole("button", { name: "Create invite" }));
    const dialog = (await screen.findAllByRole("dialog")).at(-1) as HTMLElement;
    await user.click(within(dialog).getByRole("button", { name: "Create invite" }));
    await screen.findByLabelText("Invite link");

    await user.click(screen.getByRole("button", { name: /Copy link/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Link copied"));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/#invite=SECRET-CODE`);

    await user.click(screen.getByRole("button", { name: /Copy link/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Copy failed"));
    expect(document.activeElement).toBe(screen.getByLabelText("Invite link"));
  });

  it("prefills Create from an expired row", async () => {
    const { user } = await openList([expired]);
    await user.click(screen.getByRole("button", { name: /Create a new/ }));
    expect(((await screen.findByLabelText("Who is it for? (optional)")) as HTMLInputElement).value).toBe("Zoe");
    expect(screen.getByRole("radio", { name: /Account/ }).getAttribute("aria-checked")).toBe("true");
  });
});

describe("Revoke", () => {
  it("names the person, then revokes", async () => {
    const { user, fetchMock } = await openList([unused], (url, init) =>
      url === "/api/admin/invites/u1" && init?.method === "DELETE" ? noContent() : undefined,
    );
    await user.click(screen.getByRole("button", { name: /^Revoke/ }));
    expect(await screen.findByText("Revoke this invite?")).toBeTruthy();
    expect(screen.getByText("The link for Mia stops working right away.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep it" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Revoke invite" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/admin/invites/u1" && i?.method === "DELETE")).toBe(true),
    );
  });

  it("says it was already used on a 409", async () => {
    const { user } = await openList([unused], (url, init) =>
      url === "/api/admin/invites/u1" && init?.method === "DELETE" ? json({ detail: "used" }, 409) : undefined,
    );
    await user.click(screen.getByRole("button", { name: /^Revoke/ }));
    await user.click(await screen.findByRole("button", { name: "Revoke invite" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already used");
  });
});
