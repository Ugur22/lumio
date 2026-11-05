import { describe, expect, it } from "vitest";
import type { Profile, ProfileList, TrialStatus } from "../types";
import { bannerText, hasOwnProvider, NO_TRIAL, normalizeTrial, sendBlocked, trialActive, trialBanner, trialFailure, TRIAL_ENDED, TRIAL_FULL } from "./trial";

const status = (over: Partial<TrialStatus> = {}): TrialStatus => ({ enrolled: true, limit: 5, used: 2, remaining: 3, ended: false, ...over });
const profile = (managed: boolean) => ({ id: managed ? "trial" : "own", managed }) as Profile;

describe("normalizeTrial", () => {
  it("passes a well-formed enrolled status through", () => {
    expect(normalizeTrial(status())).toEqual(status());
  });

  it.each([undefined, null, "x", 3, {}, { enrolled: false, limit: 5, remaining: 5 }])("reads %j as no trial", (raw) => {
    expect(normalizeTrial(raw)).toEqual(NO_TRIAL);
  });

  it("repairs missing, negative or oversized counts instead of throwing", () => {
    expect(normalizeTrial({ enrolled: true })).toEqual({ enrolled: true, limit: 0, used: 0, remaining: 0, ended: false });
    expect(normalizeTrial({ enrolled: true, limit: 5, used: -1, remaining: 99, ended: false })).toMatchObject({ used: 0, remaining: 5 });
  });
});

describe("trialBanner", () => {
  it("is absent for people without a trial or before the answer", () => {
    expect(trialBanner(undefined)).toBeNull();
    expect(trialBanner(NO_TRIAL)).toBeNull();
  });

  it("counts down with the server's limit, not a fixed one", () => {
    const b = trialBanner(status({ limit: 8, remaining: 6 }));
    expect(b).toEqual({ kind: "remaining", remaining: 6, limit: 8 });
    expect(bannerText(b!)).toBe("6 of 8 free messages left");
  });

  it("has its own state for the last message", () => {
    const b = trialBanner(status({ remaining: 1 }));
    expect(b?.kind).toBe("last");
    expect(bannerText(b!)).toBe("Last free message");
  });

  it("ends on zero left or when the server says ended", () => {
    expect(trialBanner(status({ remaining: 0 }))?.kind).toBe("ended");
    expect(trialBanner(status({ remaining: 3, ended: true }))?.kind).toBe("ended");
  });
});

describe("trialActive", () => {
  it("is true only while an enrolled trial has messages left", () => {
    expect(trialActive(status())).toBe(true);
    expect(trialActive(status({ remaining: 0 }))).toBe(false);
    expect(trialActive(status({ ended: true }))).toBe(false);
    expect(trialActive(NO_TRIAL)).toBe(false);
    expect(trialActive(undefined)).toBe(false);
  });
});

describe("trialFailure", () => {
  it("reads a 402 as the trial having ended", () => {
    expect(trialFailure({ status: 402, message: "whatever" })).toEqual({ kind: "ended", message: TRIAL_ENDED });
  });

  it("reads a trial 503 as full for today", () => {
    expect(trialFailure({ status: 503, message: "Free trials are full today, try tomorrow" })).toEqual({ kind: "full", message: TRIAL_FULL });
  });

  it("leaves other failures, including a different 503, to the generic path", () => {
    expect(trialFailure({ status: 503, message: "Upstream unavailable" })).toBeNull();
    expect(trialFailure({ status: 500, message: "Free trials" })).toBeNull();
    expect(trialFailure(new Error("boom"))).toBeNull();
    expect(trialFailure(null)).toBeNull();
  });
});

describe("sendBlocked", () => {
  it("blocks only an ended trial on the managed provider", () => {
    const ended = status({ remaining: 0, ended: true });
    expect(sendBlocked(ended, profile(true))).toBe(true);
    expect(sendBlocked(ended, profile(false))).toBe(false);
    expect(sendBlocked(status(), profile(true))).toBe(false);
    expect(sendBlocked(undefined, profile(true))).toBe(false);
  });
});

describe("hasOwnProvider", () => {
  it("ignores the managed profile", () => {
    const list = (...p: Profile[]): ProfileList => ({ active: null, profiles: p });
    expect(hasOwnProvider(list(profile(true)))).toBe(false);
    expect(hasOwnProvider(list(profile(true), profile(false)))).toBe(true);
    expect(hasOwnProvider(undefined)).toBe(false);
  });
});
