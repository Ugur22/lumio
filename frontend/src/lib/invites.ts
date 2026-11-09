import type { InviteItem, InviteKind, InviteReason } from "../types";

const DAY = 24 * 60 * 60 * 1000;
const ENDS_SOON = 2 * DAY;

export type InviteState = "unused" | "ends-soon" | "used" | "expired" | "revoked";
export type InviteFilter = "all" | "unused" | "used" | "expired";

export const STATE_LABEL: Record<InviteState, string> = {
  unused: "Unused",
  "ends-soon": "Ends soon",
  used: "Used",
  expired: "Expired",
  revoked: "Revoked",
};

export const KIND_LABEL: Record<InviteKind, string> = { trial: "Free trial", account: "Account" };

export const noteLabel = (note: string | null, fallback: string) => note?.trim() || fallback;

// "Ends soon" is derived from `expires`; an unused row whose expiry already passed (the list is older than the
// clock) reads as expired rather than waiting for a refetch.
export function inviteState(item: InviteItem, now: number): InviteState {
  if (item.status !== "unused") return item.status;
  const left = Date.parse(item.expires) - now;
  if (left <= 0) return "expired";
  return left <= ENDS_SOON ? "ends-soon" : "unused";
}

// A revoked invite is a dead one, so it counts under Expired.
export function filterOf(state: InviteState): Exclude<InviteFilter, "all"> {
  if (state === "unused" || state === "ends-soon") return "unused";
  return state === "used" ? "used" : "expired";
}

export function countByFilter(items: InviteItem[], now: number): Record<InviteFilter, number> {
  const counts: Record<InviteFilter, number> = { all: items.length, unused: 0, used: 0, expired: 0 };
  for (const item of items) counts[filterOf(inviteState(item, now))] += 1;
  return counts;
}

export function formatDay(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

const startOfDay = (ms: number) => new Date(ms).setHours(0, 0, 0, 0);

// Whole calendar days from `now` to `then`, so "tomorrow" means tomorrow on the wall clock, not 24 hours away.
function dayGap(then: number, now: number): number {
  return Math.round((startOfDay(then) - startOfDay(now)) / DAY);
}

function untilText(expires: number, now: number): string {
  const left = expires - now;
  if (left < 60 * 60 * 1000) return "in under an hour";
  const gap = dayGap(expires, now);
  if (gap <= 0) {
    const hours = Math.floor(left / (60 * 60 * 1000));
    return `in ${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  return gap === 1 ? "tomorrow" : `in ${gap} days`;
}

// The "Valid until" cell: how long an open invite has left, or what ended it.
export function validityText(item: InviteItem, now: number): string {
  const state = inviteState(item, now);
  if (state === "used") return item.used_at ? `used ${formatDay(item.used_at)}` : "used";
  if (state === "revoked") return "revoked";
  if (state === "expired") return `ended ${formatDay(item.expires)}`;
  return untilText(Date.parse(item.expires), now);
}

// The code rides in the fragment, which a server never receives or logs.
export const inviteLink = (origin: string, code: string) => `${origin}/#invite=${code}`;

// Reads #invite=<code> once and drops it from the address bar, keeping the path, the query and any other fragment parts.
export function takeInviteFromHash(
  loc: Pick<Location, "search" | "pathname" | "hash"> = window.location,
  hist: Pick<History, "replaceState" | "state"> = window.history,
): string | null {
  const params = new URLSearchParams(loc.hash.replace(/^#/, ""));
  const code = params.get("invite");
  if (code === null) return null;
  params.delete("invite");
  const rest = params.toString();
  hist.replaceState(hist.state, "", `${loc.pathname}${loc.search}${rest ? `#${rest}` : ""}`);
  return code.trim() || null;
}

const REASON_TEXT: Record<InviteReason, string> = {
  used: "This invite was already used. Ask for a new one.",
  expired: "This invite has expired. Ask for a new one.",
  revoked: "This invite was cancelled. Ask for a new one.",
  unknown: "This invite isn't valid. Check the link or ask for a new one.",
};

export const inviteReasonText = (reason: InviteReason | null): string => REASON_TEXT[reason ?? "unknown"];
