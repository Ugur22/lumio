import { create } from "zustand";
import { api } from "../api";
import { authErrorText, isSignedInNotice, wantsInvite } from "../lib/oauth";
import type { UserView } from "../types";

// "pending" = /me has not answered yet, so neither the login screen nor the app may show.
type Status = "pending" | "anonymous" | "signedIn" | "unreachable";

interface SessionState {
  status: Status;
  user: UserView | null;
  // Why the login screen appears without the user having signed out.
  notice: string | null;
  // The notice is one an invite code can fix, so the login screen opens that field.
  inviteHint: boolean;
  // Worth saying inside the app after a sign-in that worked (the free trial was already used).
  flash: string | null;
  // Files the ?auth_error= code from the sign-in redirect under the screen it belongs on.
  reportAuthError: (code: string) => void;
  dismissFlash: () => void;
  load: () => Promise<void>;
  signIn: (user: UserView) => void;
  signOut: () => Promise<void>;
  // The server rejected the session mid-use.
  expire: () => void;
}

let loading: Promise<void> | null = null;

export const EXPIRED = "Your session has ended. Sign in again.";

export const useSession = create<SessionState>((set, get) => ({
  status: "pending",
  user: null,
  notice: null,
  inviteHint: false,
  flash: null,
  reportAuthError: (code) => {
    const text = authErrorText(code);
    set(isSignedInNotice(code) ? { flash: text } : { notice: text, inviteHint: wantsInvite(code) });
  },
  dismissFlash: () => set({ flash: null }),
  // Deduplicated: StrictMode runs the gate's effect twice and one /me is enough.
  load: () => {
    set({ status: "pending" });
    loading ??= api
      .me()
      // A leftover login-screen notice is moot once /me says there is a session.
      .then((user) => set({ status: "signedIn", user, notice: null, inviteHint: false }))
      .catch((err: unknown) => {
        const unauthorized = (err as { status?: number }).status === 401;
        set({ status: unauthorized ? "anonymous" : "unreachable", user: null });
      })
      .finally(() => {
        loading = null;
      });
    return loading;
  },
  signIn: (user) => set({ status: "signedIn", user, notice: null, inviteHint: false }),
  // Stays signed in when the request fails, so the user is never shown as out while the cookie still works.
  signOut: async () => {
    await api.logout();
    set({ status: "anonymous", user: null, notice: null, inviteHint: false, flash: null });
  },
  expire: () => {
    if (get().status === "signedIn") set({ status: "anonymous", user: null, notice: EXPIRED, flash: null });
  },
}));
