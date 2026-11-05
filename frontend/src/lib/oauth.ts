export type OAuthProvider = "google" | "github";

// A full-page navigation: the server answers with a 302 to the provider, so this is a link, never a fetch.
export const oauthStartUrl = (provider: OAuthProvider) => `/api/auth/oauth/${provider}/start`;

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
  disabled: "Free trials are not available right now.",
  trial_used: "This account already used its free trial. You can add your own provider.",
};

export const FALLBACK_AUTH_ERROR = "Sign-in failed. Try again.";

// trial_used still signs the person in, so it is a notice inside the app rather than a problem on the login screen.
export const isSignedInNotice = (code: string) => code === "trial_used";

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
