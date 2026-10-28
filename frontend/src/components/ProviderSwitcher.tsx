import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { ChevronDownIcon } from "./icons";

interface Props {
  onManage: () => void;
}

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

export function ProviderSwitcher({ onManage }: Props) {
  const { data } = useProfiles();
  const actions = useProfileActions();
  if (!data) return null;

  const active = data.profiles.find((p) => p.id === data.active);

  if (!active) {
    return (
      <button type="button" onClick={onManage} className={`ml-auto rounded-lg px-2.5 py-1 text-accent ${focus}`}>
        Add a provider
      </button>
    );
  }

  return (
    <div className="ml-auto flex min-w-0 pl-2 items-center gap-2 text-[13px] text-muted">
      <div className="relative">
        <select
          aria-label="Provider"
          value={active.id}
          onChange={(e) => void actions.activate(e.target.value)}
          className={`max-w-[10rem] appearance-none truncate rounded-lg border border-border bg-surface py-1.5 pl-3 pr-9 text-text ${focus}`}
        >
          {data.profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <ChevronDownIcon
          width={14}
          height={14}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
        />
      </div>
      <button
        type="button"
        onClick={onManage}
        title="Change model or provider settings"
        className={`min-w-0 max-w-[11rem] truncate rounded-lg px-2 py-1 hover:bg-bubble hover:text-text max-[520px]:hidden ${focus}`}
      >
        {active.model}
      </button>
    </div>
  );
}
