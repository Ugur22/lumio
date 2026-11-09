import { describe, expect, it, vi } from "vitest";
import type { InviteItem } from "../types";
import {
  countByFilter,
  inviteLink,
  inviteReasonText,
  inviteState,
  takeInviteFromHash,
  validityText,
} from "./invites";

const NOW = new Date(2026, 10, 9, 12, 0).getTime();
const at = (days: number, hours = 0) => new Date(NOW + days * 86_400_000 + hours * 3_600_000).toISOString();

const item = (over: Partial<InviteItem>): InviteItem => ({
  id: "a",
  kind: "trial",
  note: null,
  created: at(-1),
  expires: at(5),
  status: "unused",
  used_at: null,
  ...over,
});

describe("inviteState", () => {
  it("is Unused with more than two days left and Ends soon within two", () => {
    expect(inviteState(item({ expires: at(5) }), NOW)).toBe("unused");
    expect(inviteState(item({ expires: at(2) }), NOW)).toBe("ends-soon");
    expect(inviteState(item({ expires: at(0, 3) }), NOW)).toBe("ends-soon");
  });

  it("reads a lapsed unused invite as expired", () => {
    expect(inviteState(item({ expires: at(0, -1) }), NOW)).toBe("expired");
  });

  it("passes the server's other statuses through", () => {
    expect(inviteState(item({ status: "used", expires: at(-3) }), NOW)).toBe("used");
    expect(inviteState(item({ status: "revoked" }), NOW)).toBe("revoked");
  });
});

describe("countByFilter", () => {
  it("counts revoked under Expired and Ends soon under Unused", () => {
    const items = [
      item({ id: "1" }),
      item({ id: "2", expires: at(1) }),
      item({ id: "3", status: "used" }),
      item({ id: "4", status: "expired" }),
      item({ id: "5", status: "revoked" }),
    ];
    expect(countByFilter(items, NOW)).toEqual({ all: 5, unused: 2, used: 1, expired: 2 });
  });
});

describe("validityText", () => {
  it("words open invites relatively", () => {
    expect(validityText(item({ expires: at(5) }), NOW)).toBe("in 5 days");
    expect(validityText(item({ expires: at(1) }), NOW)).toBe("tomorrow");
    expect(validityText(item({ expires: at(0, 5) }), NOW)).toBe("in 5 hours");
    expect(validityText(item({ expires: at(0, 0.5) }), NOW)).toBe("in under an hour");
  });

  it("says when a used or ended invite ended", () => {
    expect(validityText(item({ status: "used", used_at: new Date(2026, 9, 27, 12).toISOString() }), NOW)).toBe("used 27 Oct");
    expect(validityText(item({ status: "expired", expires: new Date(2026, 10, 3, 12).toISOString() }), NOW)).toBe("ended 3 Nov");
    expect(validityText(item({ status: "revoked" }), NOW)).toBe("revoked");
  });
});

describe("inviteLink", () => {
  it("puts the code in the fragment", () => {
    expect(inviteLink("https://lumio.example", "abc_-1")).toBe("https://lumio.example/#invite=abc_-1");
  });
});

describe("takeInviteFromHash", () => {
  it("returns the code and clears only the fragment", () => {
    const replaceState = vi.fn();
    const code = takeInviteFromHash(
      { pathname: "/chat", search: "?a=1", hash: "#invite=abc123" },
      { replaceState, state: { k: 1 } },
    );
    expect(code).toBe("abc123");
    expect(replaceState).toHaveBeenCalledWith({ k: 1 }, "", "/chat?a=1");
  });

  it("keeps other fragment parts", () => {
    const replaceState = vi.fn();
    takeInviteFromHash({ pathname: "/", search: "", hash: "#x=1&invite=abc" }, { replaceState, state: null });
    expect(replaceState).toHaveBeenCalledWith(null, "", "/#x=1");
  });

  it("does nothing without an invite", () => {
    const replaceState = vi.fn();
    expect(takeInviteFromHash({ pathname: "/", search: "", hash: "#other" }, { replaceState, state: null })).toBeNull();
    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe("inviteReasonText", () => {
  it("words each reason and falls back to unknown", () => {
    expect(inviteReasonText("used")).toBe("This invite was already used. Ask for a new one.");
    expect(inviteReasonText("expired")).toBe("This invite has expired. Ask for a new one.");
    expect(inviteReasonText("revoked")).toBe("This invite was cancelled. Ask for a new one.");
    expect(inviteReasonText(null)).toBe("This invite isn't valid. Check the link or ask for a new one.");
  });
});
