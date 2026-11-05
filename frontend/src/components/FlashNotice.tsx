import { useSession } from "../store/session";
import { CloseIcon } from "./icons";
import { Button } from "./ui";

// What the sign-in redirect left for the app to say once (the account had already used its free trial).
export function FlashNotice({ onAddProvider }: { onAddProvider: () => void }) {
  const flash = useSession((s) => s.flash);
  if (!flash) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-note-bg px-5 py-2 text-[13px] max-[720px]:px-3">
      <span className="min-w-0 flex-1">{flash}</span>
      <Button variant="bare" onClick={onAddProvider} className="rounded px-2 py-1 font-medium underline">
        Add provider
      </Button>
      <Button
        variant="bare"
        aria-label="Dismiss"
        onClick={() => useSession.getState().dismissFlash()}
        className="grid size-7 place-items-center rounded-full text-muted hover:text-text"
      >
        <CloseIcon width={16} height={16} />
      </Button>
    </div>
  );
}
