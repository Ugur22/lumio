import { DialogTitle } from "@headlessui/react";
import { useRef, useState } from "react";
import { formatDay, inviteLink, noteLabel } from "../lib/invites";
import type { InviteCreated } from "../types";
import { CheckIcon, CopyIcon } from "./icons";
import { Button, Modal, PressButton, TextInput } from "./ui";

interface Props {
  // Kept after closing so the panel does not go blank while it animates out.
  created: InviteCreated | null;
  open: boolean;
  onClose: () => void;
  onAnother: () => void;
}

type Copy = "idle" | "copied" | "failed";

export function InviteReadyDialog({ created, open, onClose, onAnother }: Props) {
  return (
    <Modal open={open} onClose={onClose} className="w-[min(92vw,30rem)]">
      {created && <Ready created={created} onClose={onClose} onAnother={onAnother} />}
    </Modal>
  );
}

function Ready({ created, onClose, onAnother }: { created: InviteCreated; onClose: () => void; onAnother: () => void }) {
  const [copy, setCopy] = useState<Copy>("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const link = inviteLink(window.location.origin, created.code);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link);
      setCopy("copied");
    } catch {
      // No clipboard permission (or an insecure origin): leave the link selected so Ctrl/Cmd+C works.
      setCopy("failed");
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }

  return (
    <div className="flex flex-col gap-4 p-5">
      <DialogTitle as="h2" className="font-display text-lg font-semibold">
        Invite ready
      </DialogTitle>
      <div className="flex flex-col gap-2">
        <TextInput
          ref={inputRef}
          readOnly
          aria-label="Invite link"
          value={link}
          onFocus={(e) => e.currentTarget.select()}
          className="w-full font-mono text-[13px]"
        />
        <div className="flex flex-wrap items-center gap-3">
          <PressButton onClick={() => void copyLink()} hover={1.02} press={0.97} variant="secondary">
            <CopyIcon width={16} height={16} className="mr-1.5 inline" />
            Copy link
          </PressButton>
          {/* Always rendered, so the live region exists before its text changes and the change is announced. */}
          <p role="status" className={`flex items-center gap-1.5 text-[13px] empty:hidden ${copy === "failed" ? "text-warn-bar" : "text-muted"}`}>
            {copy === "copied" && (
              <>
                <CheckIcon width={16} height={16} className="text-accent" />
                Link copied
              </>
            )}
            {copy === "failed" && "Copy failed. The link is selected, copy it by hand."}
          </p>
        </div>
      </div>
      <p className="rounded-lg bg-note-bg px-3 py-2 text-[13px]">
        This link works once and can&apos;t be shown again. It expires on {formatDay(created.expires)}.
      </p>
      <p className="text-[13px] text-muted">
        Send it to {noteLabel(created.note, "them")} yourself. Lumio doesn&apos;t send messages.
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button onClick={onAnother}>Create another</Button>
        <PressButton onClick={onClose} hover={1.02} press={0.97} variant="primary">
          Done
        </PressButton>
      </div>
    </div>
  );
}
