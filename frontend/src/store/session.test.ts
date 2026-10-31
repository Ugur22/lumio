import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { resetSession, alice } from "../test/helpers";
import { EXPIRED, useSession } from "./session";

beforeEach(resetSession);
afterEach(() => vi.restoreAllMocks());

describe("session store", () => {
  it("loads the user from /me", async () => {
    vi.spyOn(api, "me").mockResolvedValue(alice);
    await useSession.getState().load();
    expect(useSession.getState()).toMatchObject({ status: "signedIn", user: alice });
  });

  it("is anonymous on a 401", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError("Not signed in", 401));
    await useSession.getState().load();
    expect(useSession.getState().status).toBe("anonymous");
  });

  it("reports an unreachable server instead of showing the login screen", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new TypeError("Failed to fetch"));
    await useSession.getState().load();
    expect(useSession.getState().status).toBe("unreachable");
  });

  it("asks /me once for concurrent loads", async () => {
    const me = vi.spyOn(api, "me").mockResolvedValue(alice);
    await Promise.all([useSession.getState().load(), useSession.getState().load()]);
    expect(me).toHaveBeenCalledTimes(1);
  });

  it("expires only a signed-in session, with a notice", () => {
    useSession.getState().expire();
    expect(useSession.getState().status).toBe("pending");
    useSession.getState().signIn(alice);
    useSession.getState().expire();
    expect(useSession.getState()).toMatchObject({ status: "anonymous", user: null, notice: EXPIRED });
  });

  it("signs out through the API, and stays signed in if that fails", async () => {
    useSession.getState().signIn(alice);
    vi.spyOn(api, "logout").mockRejectedValueOnce(new TypeError("offline"));
    await expect(useSession.getState().signOut()).rejects.toThrow();
    expect(useSession.getState().status).toBe("signedIn");
    vi.spyOn(api, "logout").mockResolvedValueOnce(undefined);
    await useSession.getState().signOut();
    expect(useSession.getState()).toMatchObject({ status: "anonymous", user: null, notice: null });
  });
});
