import type { Profile, ProfileList, TrialStatus } from "../types";

export const TRIAL_ENDED = "Your free trial has ended. Add your own provider to continue.";
export const TRIAL_FULL = "Free trials are full today, try tomorrow";
export const TRIAL_LOCKED = "Adding your own provider unlocks when your free trial ends.";
// Shown before sign-in, when the real limit is not known yet; the signed-in UI reads it from /api/trial.
export const TRIAL_PITCH = "Free trial: 5 messages, no card";

export const NO_TRIAL: TrialStatus = { enrolled: false, limit: 0, used: 0, remaining: 0, ended: false };

const count = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0);

// A missing or malformed answer reads as "no trial", so a quirk never locks anyone out of the app.
export function normalizeTrial(raw: unknown): TrialStatus {
  if (typeof raw !== "object" || raw === null) return NO_TRIAL;
  const r = raw as Record<string, unknown>;
  if (r.enrolled !== true) return NO_TRIAL;
  const limit = count(r.limit);
  return {
    enrolled: true,
    limit,
    used: count(r.used),
    remaining: Math.min(count(r.remaining), limit),
    ended: r.ended === true,
  };
}

const over = (t: TrialStatus) => t.ended || t.remaining <= 0;

// The trial is running: the person has not used it up and the server still has the managed provider on.
export const trialActive = (t: TrialStatus | undefined): boolean => Boolean(t?.enrolled && !over(t));

export type TrialBanner =
  | { kind: "remaining"; remaining: number; limit: number }
  | { kind: "last"; limit: number }
  | { kind: "ended" };

export function trialBanner(t: TrialStatus | undefined): TrialBanner | null {
  if (!t?.enrolled) return null;
  if (over(t)) return { kind: "ended" };
  if (t.remaining === 1) return { kind: "last", limit: t.limit };
  return { kind: "remaining", remaining: t.remaining, limit: t.limit };
}

export function bannerText(b: TrialBanner): string {
  switch (b.kind) {
    case "remaining":
      return `${b.remaining} of ${b.limit} free messages left`;
    case "last":
      return "Last free message";
    case "ended":
      return "Free trial ended";
  }
}

export type TrialFailure = { kind: "ended" | "full"; message: string };

// 402 and 503 on a send are the trial speaking, not a fault. A 503 from anything else stays a generic error.
export function trialFailure(err: unknown): TrialFailure | null {
  if (typeof err !== "object" || err === null) return null;
  const { status, message } = err as { status?: unknown; message?: unknown };
  if (status === 402) return { kind: "ended", message: TRIAL_ENDED };
  if (status === 503 && typeof message === "string" && /free trial/i.test(message)) {
    return { kind: "full", message: TRIAL_FULL };
  }
  return null;
}

export const isManaged = (p: Profile | undefined): boolean => p?.managed === true;

export const hasOwnProvider = (list: ProfileList | undefined): boolean =>
  Boolean(list?.profiles.some((p) => !p.managed));

// Whether sending would only bounce off a 402: the trial is used up and the provider in force is the trial's.
export function sendBlocked(t: TrialStatus | undefined, active: Profile | undefined): boolean {
  return isManaged(active) && trialBanner(t)?.kind === "ended";
}
