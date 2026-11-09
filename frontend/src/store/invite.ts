import { create } from "zustand";
import { api } from "../api";
import { takeInviteFromHash } from "../lib/invites";
import type { InviteKind, InviteReason } from "../types";

// checking: the one invite-check call is in flight. unchecked: it could not be answered (offline, throttled),
// so the code is still carried along and the server decides at sign-in.
type Phase = "none" | "checking" | "applied" | "invalid" | "unchecked";

interface InviteLinkState {
  phase: Phase;
  // The code from the link. It lives here only until sign-in or removal, and is never written to storage.
  code: string | null;
  kind: InviteKind | null;
  reason: InviteReason | null;
  // Why the check could not run, worded for the card.
  problem: string | null;
  start: () => void;
  remove: () => void;
}

const NONE = { phase: "none", code: null, kind: null, reason: null, problem: null } as const;

let started = false;

// invite-check is throttled and every call counts, so the link is read and checked once per page load; StrictMode's
// second effect run, and a later remount of the login screen, find `started` set.
export const useInviteLink = create<InviteLinkState>((set) => ({
  ...NONE,
  start: () => {
    if (started) return;
    started = true;
    const code = takeInviteFromHash();
    if (!code) return;
    set({ ...NONE, phase: "checking", code });
    api
      .checkInvite(code)
      .then((res) => {
        if (res.valid && res.kind) set({ phase: "applied", kind: res.kind, reason: null });
        else set({ phase: "invalid", code: null, reason: res.reason ?? "unknown" });
      })
      .catch((err: unknown) => {
        const throttled = (err as { status?: number }).status === 429;
        set({
          phase: "unchecked",
          problem: throttled
            ? "Too many checks from your network. You can still try the invite."
            : "Could not check this invite. You can still try it.",
        });
      });
  },
  remove: () => set({ ...NONE }),
}));

// Tests only: lets each case start from a fresh page load.
export function resetInviteLink() {
  started = false;
  useInviteLink.setState({ ...NONE });
}
