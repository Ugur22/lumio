import { describe, expect, it } from "vitest";
import type { ProfileList, TrialStatus } from "../types";
import { emptyKind } from "./emptyProviders";
import { NO_TRIAL } from "./trial";

const profile = (id: string, managed: boolean) => ({ id, name: id, managed }) as ProfileList["profiles"][number];
const none: ProfileList = { active: null, profiles: [] };
const own: ProfileList = { active: "a", profiles: [profile("a", false)] };
const managedOnly: ProfileList = { active: "m", profiles: [profile("m", true)] };
const running: TrialStatus = { enrolled: true, limit: 5, used: 2, remaining: 3, ended: false };
const used: TrialStatus = { enrolled: true, limit: 5, used: 5, remaining: 0, ended: true };

describe("emptyKind", () => {
  it("is new for an account with no provider and no trial", () => {
    expect(emptyKind(none, NO_TRIAL, true)).toBe("new");
    expect(emptyKind(none, undefined, true)).toBe("new");
  });

  it("is ended once the trial is used up and nothing replaced it", () => {
    expect(emptyKind(managedOnly, used, true)).toBe("ended");
    expect(emptyKind(none, used, true)).toBe("ended");
  });

  it("is silent when the person has their own provider", () => {
    expect(emptyKind(own, NO_TRIAL, true)).toBeNull();
    expect(emptyKind(own, used, true)).toBeNull();
  });

  it("is silent while the trial is running", () => {
    expect(emptyKind(managedOnly, running, true)).toBeNull();
  });

  it("is silent until profiles and the trial answer are both in", () => {
    expect(emptyKind(undefined, NO_TRIAL, true)).toBeNull();
    expect(emptyKind(none, undefined, false)).toBeNull();
    expect(emptyKind(undefined, undefined, false)).toBeNull();
  });
});
