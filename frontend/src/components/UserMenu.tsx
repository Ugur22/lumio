import { Menu, MenuButton, MenuItem, MenuItems } from "@headlessui/react";
import { useState } from "react";
import { authErrorMessage } from "../lib/auth";
import { useSession } from "../store/session";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { ChevronUpIcon, KeyIcon, LogOutIcon, UserIcon } from "./icons";
import { focusRing } from "./ui";

const item = `flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-muted data-[focus]:bg-bubble data-[focus]:text-text`;

// Local runs have one fixed user and no session to end, so there is nothing to show.
export function UserMenu() {
  const user = useSession((s) => s.user);
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user || user.id === "local") return null;

  async function signOut() {
    setError(null);
    try {
      await useSession.getState().signOut();
    } catch (err) {
      setError(authErrorMessage(err));
    }
  }

  return (
    <div className="relative">
      <Menu>
        <MenuButton
          className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-muted hover:bg-bubble hover:text-text ${focusRing}`}
        >
          <UserIcon />
          <span className="min-w-0 flex-1 truncate" title={user.username}>
            {user.username}
          </span>
          <ChevronUpIcon width={16} height={16} />
        </MenuButton>
        <MenuItems
          className={`absolute inset-x-0 bottom-full z-10 mb-1 flex flex-col rounded-xl border border-border bg-surface p-1 shadow-lift ${focusRing}`}
        >
          <MenuItem>
            <button type="button" className={item} onClick={() => setChanging(true)}>
              <KeyIcon /> Change password
            </button>
          </MenuItem>
          <MenuItem>
            <button type="button" className={item} onClick={() => void signOut()}>
              <LogOutIcon /> Sign out
            </button>
          </MenuItem>
        </MenuItems>
      </Menu>
      {error && (
        <p role="alert" className="px-2.5 pt-1 text-[12px] text-warn-bar">
          {error}
        </p>
      )}
      <ChangePasswordDialog open={changing} onClose={() => setChanging(false)} />
    </div>
  );
}
