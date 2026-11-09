import { DialogTitle } from "@headlessui/react";
import { useRef, useState } from "react";
import { useInviteActions, useInvites } from "../hooks/useInvites";
import { authErrorMessage } from "../lib/auth";
import { countByFilter, noteLabel, type InviteFilter } from "../lib/invites";
import type { InviteCreated, InviteItem } from "../types";
import { CreateInviteDialog, type InvitePreset } from "./CreateInviteDialog";
import { CloseIcon, PlusIcon } from "./icons";
import { InviteReadyDialog } from "./InviteReadyDialog";
import { InvitesTable } from "./InvitesTable";
import { Button, ConfirmDialog, Modal, PressButton, cx, focusRing } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

const FILTERS: { id: InviteFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "unused", label: "Unused" },
  { id: "used", label: "Used" },
  { id: "expired", label: "Expired" },
];

type Create = { open: boolean; preset: InvitePreset | null };

// A dialog rather than a route, like the Providers dialog: the app has no router, and this is a task done from a menu.
export function InvitesDialog({ open, onClose }: Props) {
  const invites = useInvites(open);
  const actions = useInviteActions();
  const [filter, setFilter] = useState<InviteFilter>("all");
  const [create, setCreate] = useState<Create>({ open: false, preset: null });
  const [ready, setReady] = useState<{ created: InviteCreated | null; open: boolean }>({ created: null, open: false });
  const [revoking, setRevoking] = useState<InviteItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const busy = useRef(false);

  // The clock is the time the list arrived, so rows do not change under the admin's cursor.
  const now = invites.dataUpdatedAt;
  const items = invites.data ?? [];
  const counts = countByFilter(items, now);

  function close() {
    setNotice(null);
    setFilter("all");
    setReady({ created: null, open: false });
    onClose();
  }

  async function confirmRevoke() {
    if (!revoking || busy.current) return;
    busy.current = true;
    const target = revoking;
    try {
      await actions.revoke(target.id);
      setNotice(null);
    } catch (err) {
      const status = (err as { status?: number }).status;
      setNotice(status === 409 ? "That invite was already used, so it can't be revoked." : authErrorMessage(err));
    } finally {
      busy.current = false;
      setRevoking(null);
    }
  }

  return (
    <Modal open={open} onClose={close} className="w-[min(96vw,56rem)]">
      <div className="flex flex-col gap-4 p-5 max-[480px]:p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <DialogTitle as="h2" className="font-display text-lg font-semibold">
              Invites
            </DialogTitle>
            <p className="text-[13px] text-muted">Codes for people you want to give a free trial or an account.</p>
          </div>
          <PressButton onClick={() => setCreate({ open: true, preset: null })} hover={1.02} press={0.97} variant="primary">
            <PlusIcon width={16} height={16} />
            Create invite
          </PressButton>
          <button
            type="button"
            aria-label="Close"
            onClick={close}
            className={cx("grid size-9 flex-none place-items-center rounded-lg text-muted hover:bg-bubble hover:text-text", focusRing)}
          >
            <CloseIcon width={18} height={18} />
          </button>
        </div>

        <div role="group" aria-label="Filter invites" className="flex flex-wrap gap-2">
          {FILTERS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className={cx(
                "rounded-full border px-3 py-1 text-[13px]",
                filter === id ? "border-accent bg-bubble font-medium text-text" : "border-border text-muted hover:text-text",
                focusRing,
              )}
            >
              {label} <span className="tabular-nums">{counts[id]}</span>
            </button>
          ))}
        </div>

        {notice && (
          <p role="alert" className="rounded-lg bg-warn-bg px-3 py-2 text-[13px] text-warn-bar">
            {notice}
          </p>
        )}

        {invites.isLoading && <p className="py-6 text-center text-muted">Loading…</p>}
        {invites.isError && (
          <div role="alert" className="flex flex-col items-center gap-2 py-6 text-center">
            <p className="text-warn-bar">{authErrorMessage(invites.error)}</p>
            <Button variant="secondary" onClick={() => void invites.refetch()}>
              Try again
            </Button>
          </div>
        )}
        {invites.data && (
          <InvitesTable
            items={items}
            filter={filter}
            now={now}
            onRevoke={setRevoking}
            onRenew={(item) => setCreate({ open: true, preset: { note: item.note ?? "", kind: item.kind } })}
          />
        )}

        <p className="text-[13px] text-muted">
          A code can&apos;t be shown again after it is created. If one is lost, revoke it and make a new one.
        </p>
      </div>

      <CreateInviteDialog
        open={create.open}
        preset={create.preset}
        onClose={() => setCreate((c) => ({ ...c, open: false }))}
        create={actions.create}
        onCreated={(created) => {
          setCreate((c) => ({ ...c, open: false }));
          setReady({ created, open: true });
        }}
      />
      <InviteReadyDialog
        created={ready.created}
        open={ready.open}
        onClose={() => setReady((r) => ({ ...r, open: false }))}
        onAnother={() => {
          setReady((r) => ({ ...r, open: false }));
          setCreate({ open: true, preset: null });
        }}
      />
      <ConfirmDialog
        open={revoking !== null}
        danger
        title="Revoke this invite?"
        description={`The link for ${noteLabel(revoking?.note ?? null, "this person")} stops working right away.`}
        confirmLabel="Revoke invite"
        cancelLabel="Keep it"
        onConfirm={() => void confirmRevoke()}
        onCancel={() => setRevoking(null)}
      />
    </Modal>
  );
}
