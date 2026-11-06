export type OAuthProvider = "google" | "github";

// A full-page navigation: the server answers with a 302 to the provider, so this is a link, never a fetch.
// The invite is a one-time secret: trimmed, encoded, and only ever put in this navigation URL.
export const oauthStartUrl = (provider: OAuthProvider, invite = "") => {
  const code = invite.trim();
  const base = `/api/auth/oauth/${provider}/start`;
  return code ? `${base}?invite=${encodeURIComponent(code)}` : base;
};

// The codes the callback puts in /?auth_error=. Only these are ever shown; the URL's own text never reaches the page.
const MESSAGES: Record<string, string> = {
  unavailable: "Sign-in with that provider is not available right now.",
  state: "That sign-in expired or was interrupted. Try again.",
  denied: "Sign-in was cancelled.",
  provider: "The provider could not complete the sign-in. Try again in a moment.",
  unverified: "Your email must be verified",
  too_new: "That GitHub account is too new to start a trial",
  disposable: "Disposable email addresses cannot start a trial",
  throttled: "Too many sign-ups from your network, try later",
  invite: "That invite code isn't valid. It may be used, expired or mistyped.",
  open_full: "Free trials are full for today. If you have an invite code, enter it below.",
  reserved_full: "Invited sign-ups are full for today. Your invite code is still valid, try again tomorrow.",
  disabled: "Free trials are not available right now.",
  trial_used: "This account already used its free trial. You can add your own provider.",
};

export const FALLBACK_AUTH_ERROR = "Sign-in failed. Try again.";

// trial_used still signs the person in, so it is a notice inside the app rather than a problem on the login screen.
export const isSignedInNotice = (code: string) => code === "trial_used";

// Errors the person can fix by entering an invite code.
export const wantsInvite = (code: string) => code === "invite" || code === "open_full";

export const authErrorText = (code: string): string =>
  Object.hasOwn(MESSAGES, code) ? (MESSAGES[code] as string) : FALLBACK_AUTH_ERROR;

// Reads ?auth_error= once and removes it from the address bar so a reload or a shared link does not replay it.
export function takeAuthError(
  loc: Pick<Location, "search" | "pathname" | "hash"> = window.location,
  hist: Pick<History, "replaceState" | "state"> = window.history,
): string | null {
  const params = new URLSearchParams(loc.search);
  const code = params.get("auth_error");
  if (code === null) return null;
  params.delete("auth_error");
  const rest = params.toString();
  hist.replaceState(hist.state, "", `${loc.pathname}${rest ? `?${rest}` : ""}${loc.hash}`);
  return code;
}
