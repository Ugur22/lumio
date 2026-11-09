import { DialogTitle, Field, Label, Description, Radio, RadioGroup } from "@headlessui/react";
import { useState, type FormEvent } from "react";
import { authErrorMessage } from "../lib/auth";
import type { InviteCreated, InviteKind } from "../types";
import { Button, Modal, PressButton, TextField } from "./ui";

export interface InvitePreset {
  note: string;
  kind: InviteKind;
}

interface Props {
  open: boolean;
  preset: InvitePreset | null;
  onClose: () => void;
  create: (body: { kind: InviteKind; note: string | null }) => Promise<InviteCreated>;
  onCreated: (created: InviteCreated) => void;
}

const KINDS: { kind: InviteKind; title: string; text: string }[] = [
  { kind: "trial", title: "Free trial", text: "They sign in with Google or GitHub and get 5 free replies." },
  { kind: "account", title: "Account", text: "They register with a username and password." },
];

export function CreateInviteDialog({ open, preset, onClose, create, onCreated }: Props) {
  return (
    <Modal open={open} onClose={onClose} className="w-[min(92vw,28rem)]">
      <CreateForm preset={preset} onClose={onClose} create={create} onCreated={onCreated} />
    </Modal>
  );
}

// Mounts only while the dialog is open, so every opening starts from the preset (or blank).
function CreateForm({ preset, onClose, create, onCreated }: Omit<Props, "open">) {
  const [note, setNote] = useState(preset?.note ?? "");
  const [kind, setKind] = useState<InviteKind>(preset?.kind ?? "trial");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      onCreated(await create({ kind, note: note.trim() || null }));
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 p-5">
      <DialogTitle as="h2" className="font-display text-lg font-semibold">
        Create invite
      </DialogTitle>
      <TextField
        label="Who is it for? (optional)"
        name="note"
        maxLength={80}
        autoComplete="off"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <RadioGroup value={kind} onChange={setKind} aria-label="Type" className="flex flex-col gap-2">
        {KINDS.map((k) => (
          <Field key={k.kind}>
            <Radio
              value={k.kind}
              className="flex cursor-pointer flex-col gap-0.5 rounded-xl border border-border px-3 py-2.5 data-[checked]:border-accent data-[checked]:bg-bubble data-[focus]:outline data-[focus]:outline-2 data-[focus]:outline-accent"
            >
              <Label className="cursor-pointer font-medium">{k.title}</Label>
              <Description className="text-[13px] text-muted">{k.text}</Description>
            </Radio>
          </Field>
        ))}
      </RadioGroup>
      <p className="text-[13px] text-muted">The link works for 7 days.</p>
      <p role="alert" className="text-[13px] text-warn-bar empty:sr-only">
        {error}
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <PressButton type="submit" disabled={pending} hover={1.02} press={0.97} variant="primary">
          {pending ? "Creating…" : "Create invite"}
        </PressButton>
      </div>
    </form>
  );
}
