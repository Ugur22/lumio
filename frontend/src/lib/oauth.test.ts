import { describe, expect, it, vi } from "vitest";
import { authErrorText, FALLBACK_AUTH_ERROR, isSignedInNotice, oauthStartUrl, takeAuthError } from "./oauth";

describe("oauthStartUrl", () => {
  it("points at the server's start route for each provider", () => {
    expect(oauthStartUrl("google")).toBe("/api/auth/oauth/google/start");
    expect(oauthStartUrl("github")).toBe("/api/auth/oauth/github/start");
  });
});

describe("authErrorText", () => {
  it.each([
    ["too_new", "That GitHub account is too new to start a trial"],
    ["unverified", "Your email must be verified"],
    ["disposable", "Disposable email addresses cannot start a trial"],
    ["throttled", "Too many sign-ups from your network, try later"],
    ["reserved_full", "Invited sign-ups are full for today. Your invite code is still valid, try again tomorrow."],
    ["trial_used", "This account already used its free trial. You can add your own provider."],
  ])("words %s", (code, text) => {
    expect(authErrorText(code)).toBe(text);
  });

  it.each(["unavailable", "state", "denied", "provider", "disabled"])("has a message for %s", (code) => {
    expect(authErrorText(code)).not.toBe(FALLBACK_AUTH_ERROR);
  });

  it("never echoes an unknown code from the URL", () => {
    expect(authErrorText("<b>hi</b>")).toBe(FALLBACK_AUTH_ERROR);
    expect(authErrorText("toString")).toBe(FALLBACK_AUTH_ERROR);
  });

  it("treats only trial_used as a notice for a signed-in person", () => {
    expect(isSignedInNotice("trial_used")).toBe(true);
    expect(isSignedInNotice("too_new")).toBe(false);
  });
});

describe("takeAuthError", () => {
  it("returns the code and removes it from the URL, keeping other parts", () => {
    const replaceState = vi.fn();
    const code = takeAuthError({ search: "?a=1&auth_error=denied", pathname: "/", hash: "#x" }, { replaceState, state: null });
    expect(code).toBe("denied");
    expect(replaceState).toHaveBeenCalledWith(null, "", "/?a=1#x");
  });

  it("leaves a clean path when it was the only parameter", () => {
    const replaceState = vi.fn();
    takeAuthError({ search: "?auth_error=state", pathname: "/", hash: "" }, { replaceState, state: null });
    expect(replaceState).toHaveBeenCalledWith(null, "", "/");
  });

  it("does nothing without the parameter", () => {
    const replaceState = vi.fn();
    expect(takeAuthError({ search: "?q=1", pathname: "/", hash: "" }, { replaceState, state: null })).toBeNull();
    expect(replaceState).not.toHaveBeenCalled();
  });
});
