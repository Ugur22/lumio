import { filterOf, inviteState, KIND_LABEL, noteLabel, STATE_LABEL, formatDay, validityText, type InviteFilter, type InviteState } from "../lib/invites";
import type { InviteItem } from "../types";
import { Button } from "./ui";

// The word carries the meaning; the dot only repeats it, so the pill never relies on colour alone.
const DOT: Record<InviteState, string> = {
  unused: "bg-accent",
  "ends-soon": "bg-caution",
  used: "bg-muted",
  expired: "border border-muted bg-transparent",
  revoked: "bg-warn-bar",
};

export function StatusPill({ state }: { state: InviteState }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-bg px-2.5 py-0.5 text-[12px] font-medium">
      <span aria-hidden="true" className={`size-1.5 flex-none rounded-full ${DOT[state]}`} />
      {STATE_LABEL[state]}
    </span>
  );
}

interface Props {
  items: InviteItem[];
  filter: InviteFilter;
  now: number;
  onRevoke: (item: InviteItem) => void;
  onRenew: (item: InviteItem) => void;
}

const th = "px-3 py-2 text-left text-[12px] font-medium text-muted";
const td = "px-3 py-2.5 align-middle";

export function InvitesTable({ items, filter, now, onRevoke, onRenew }: Props) {
  const rows = items.filter((i) => filter === "all" || filterOf(inviteState(i, now)) === filter);
  if (rows.length === 0) return <p className="px-3 py-6 text-center text-muted">No invites here.</p>;

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[40rem] border-collapse text-[14px]">
        <thead className="border-b border-border bg-bg">
          <tr>
            <th scope="col" className={th}>Note</th>
            <th scope="col" className={th}>Type</th>
            <th scope="col" className={th}>Created</th>
            <th scope="col" className={th}>Valid until</th>
            <th scope="col" className={th}>Status</th>
            <th scope="col" className={th}>
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => {
            const state = inviteState(item, now);
            const who = noteLabel(item.note, "this person");
            return (
              <tr key={item.id} className="border-b border-border last:border-b-0">
                {/* Server text: rendered as a React text child, so it is always plain text. */}
                <td className={`${td} max-w-[14rem]`}>
                  <span className={`block truncate ${item.note?.trim() ? "" : "text-muted"}`} title={item.note ?? undefined}>
                    {noteLabel(item.note, "No note")}
                  </span>
                </td>
                <td className={`${td} whitespace-nowrap`}>{KIND_LABEL[item.kind]}</td>
                <td className={`${td} whitespace-nowrap text-muted`}>{formatDay(item.created)}</td>
                <td className={`${td} whitespace-nowrap text-muted`}>{validityText(item, now)}</td>
                <td className={td}>
                  <StatusPill state={state} />
                </td>
                <td className={`${td} text-right`}>
                  {(state === "unused" || state === "ends-soon") && (
                    <Button variant="danger" aria-label={`Revoke invite for ${who}`} onClick={() => onRevoke(item)}>
                      Revoke
                    </Button>
                  )}
                  {state === "expired" && (
                    <Button variant="link" className="text-[13px]" aria-label={`Create a new invite like the one for ${who}`} onClick={() => onRenew(item)}>
                      Create a new one
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
